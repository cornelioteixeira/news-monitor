"""Pipeline: RSS -> dedup -> Groq (filtro+resumo) -> Neonize (com link oficial)."""
import hashlib
import html
import json
import logging
import os
import re
import time

import feedparser

import config
import groq_service
import whatsapp_service
from feeds import FEEDS

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _item_id(feed_name: str, link: str, title: str) -> str:
    base = link or f"{feed_name}:{title}"
    return hashlib.sha256(base.encode("utf-8", "ignore")).hexdigest()[:16]


def load_seen() -> set:
    if not os.path.exists(config.SEEN_FILE):
        return set()
    try:
        with open(config.SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen: set) -> None:
    try:
        with open(config.SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(seen)[-2000:], f)
    except Exception as e:
        log.warning("save_seen: %s", e)


def fetch_all_feeds() -> list[dict]:
    """Lê todos os feeds e retorna itens novos (não vistos)."""
    seen = load_seen()
    fresh: list[dict] = []
    for feed in FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
            if parsed.bozo and not parsed.entries:
                log.warning("Feed %s vazio/erro: %s", feed["name"], parsed.bozo_exception)
            for e in parsed.entries[:20]:  # limite por feed p/ controlar volume
                link = (getattr(e, "link", "") or "").strip()
                title = _clean(getattr(e, "title", "sem título"))
                snippet = _clean(getattr(e, "summary", getattr(e, "description", ""))[:2000])
                iid = _item_id(feed["name"], link, title)
                if iid in seen or not link:
                    continue
                fresh.append(
                    {
                        "id": iid,
                        "title": title,
                        "link": link,  # <-- link oficial preservado até a mensagem
                        "snippet": snippet,
                        "source": feed["name"],
                        "company": feed.get("company", ""),
                        "official": bool(feed.get("official")),
                    }
                )
        except Exception as e:
            log.error("fetch %s: %s", feed["name"], e)
    # marca como vistos já na coleta p/ não repetir em próxima rodada
    if fresh:
        save_seen(seen | {i["id"] for i in fresh})
    log.info("Coletados %d itens novos", len(fresh))
    return fresh[: config.MAX_ITEMS_PER_RUN]


HEADER_RE = re.compile(
    r"^\s*(resumo(\s+em\s+\d+\s+pontos.*)?|summary|introdu[cç][aã]o|conclus[aã]o|fonte\s*:.*|refer[eê]ncia\s*:.*)\s*:?\s*$",
    re.IGNORECASE,
)


def _sanitize_resumo(resumo: str, fallback_title: str = "") -> str:
    """Limpa markdown inventado pelo Groq e normaliza o corpo da mensagem.

    O WhatsApp renderiza *negrito* e _itálico_ pelos marcadores — por isso o
    corpo usa texto puro e os marcadores vivem só no template (títulos/rodapé).
    """
    text = (resumo or "").replace("**", "").replace("__", "")
    text = text.replace("`", "")
    raw_lines = [ln.strip() for ln in text.splitlines()]
    lines: list[str] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].replace("*", "").strip().removeprefix("#").strip()
        i += 1
        if not line:
            continue
        if HEADER_RE.match(line):
            continue
        if line.startswith(("- ", "· ")):
            line = "• " + line[2:].strip()
        m = re.match(r"(?i)^por que importa\s*:\s*(.*)$", line)
        if m:
            corpo = m.group(1).strip().replace("*", "")
            if not corpo:  # "Por que importa:" vazio → usa a próxima linha como corpo
                while i < len(raw_lines):
                    nxt = raw_lines[i].replace("*", "").strip()
                    i += 1
                    if nxt and not HEADER_RE.match(nxt):
                        corpo = nxt
                        break
            if corpo:
                lines.append(f"_Por que importa:_ {corpo}")
            continue
        lines.append(line)
    clean = "\n".join(lines).strip().strip("*").strip()
    if not clean and fallback_title:
        clean = f"• {fallback_title.strip().strip('*')}\n_Por que importa:_ ver artigo oficial."
    return clean


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "sem título").replace("*", "")).strip()


def format_single(item: dict, resumo_pt: str, categoria: str) -> str:
    """Mensagem individual — SEMPRE com link do artigo oficial (requisito)."""
    badge = "🏛️ *Novidade Oficial*" if item["official"] else f"🤖 *{categoria}*"
    title = _clean_title(item["title"])
    corpo = _sanitize_resumo(resumo_pt, fallback_title=title)
    return (
        f"{badge}\n"
        f"*{title}*\n\n"
        f"{corpo}\n\n"
        f"🔗 Artigo oficial: {item['link']}\n"
        f"📰 Fonte: {item['source']}"
    )


def format_digest(items: list[dict]) -> str:
    """Digest agrupado: 1 mensagem com N resumos, cada um com seu link."""
    lines = ["🗞️ *Digest IA*"]
    lines.append(f"_Manchetes de IA resumidas em português — {len(items)} novidades_\n")
    for n, it in enumerate(items, 1):
        title = _clean_title(it["title"])
        corpo = _sanitize_resumo(it.get("resumo", ""), fallback_title=title)
        lines.append(f"*{n}. {title}*")
        lines.append(corpo)
        lines.append(f"🔗 {it['link']}")
        if n < len(items):
            lines.append("───────────────")
    lines.append("\n_Enviado pelo teu bot de IA 🤖_")
    text = "\n".join(lines)
    return text[:3800]  # margem anti-corte do WhatsApp


def process_all_news() -> dict:
    """Entry-point chamado pelo endpoint/scheduler. Retorna estatísticas."""
    t0 = time.time()
    items = fetch_all_feeds()
    if not items:
        return {"status": "sem_novidades", "enviadas": 0}

    urgentes, digest_candidatos = [], []
    for it in items:
        cls = groq_service.classify(it["title"], it["snippet"], it["source"])
        it.update(cls)
        score = cls["score"]
        if score >= config.SCORE_SEND_NOW:
            urgentes.append(it)
        elif score >= config.SCORE_DIGEST_MIN:
            digest_candidatos.append(it)
        else:
            log.info("Descartado (score %d): %s", score, it["title"][:80])

    enviadas = 0
    # 1) Urgentes vão na hora, 1 mensagem cada (com link oficial), com pausa anti-spam
    for it in urgentes[: config.MAX_ITEMS_PER_RUN]:
        resumo = groq_service.summarize_pt(it["title"], it["snippet"], it["link"], it["categoria"])
        msg = format_single(it, resumo, it["categoria"])
        if whatsapp_service.send_text(msg):
            enviadas += 1
        time.sleep(4)  # evita rajada -> anti-spam

    # 2) Médios vão em digest único agrupado
    digest_candidatos = digest_candidatos[: config.MAX_DIGEST_ITEMS]
    if digest_candidatos:
        for it in digest_candidatos:
            it["resumo"] = groq_service.summarize_pt(it["title"], it["snippet"], it["link"], it["categoria"])
            time.sleep(1)
        if whatsapp_service.send_text(format_digest(digest_candidatos)):
            enviadas += 1  # 1 mensagem de digest

    dt = round(time.time() - t0, 1)
    log.info("process_all_news: enviadas=%d urgentes=%d digest=%d em %ss", enviadas, len(urgentes), len(digest_candidatos), dt)
    return {
        "status": "ok",
        "coletados": len(items),
        "urgentes": len(urgentes),
        "digest": len(digest_candidatos),
        "enviadas": enviadas,
        "segundos": dt,
    }
