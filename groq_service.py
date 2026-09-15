"""Wrapper Groq: classificação de relevância + resumo/tradução PT."""
import json
import logging
from groq import Groq

import config

log = logging.getLogger(__name__)

SYSTEM_CLASSIFIER = (
    "Você é um curador de notícias de IA. Responda SEMPRE em JSON válido, sem markdown. "
    'Schema: {"score": int 0-10, "categoria": "Novidade Oficial" | "Polémica IA" | "Técnico" | "Produto" | "Ruído", '
    '"motivo": str curto}. '
    "Se a fonte for blog oficial (Anthropic, OpenAI, Groq), tenda a categoria 'Novidade Oficial' "
    "quando for lançamento/anúncio real. 8-10 = urgente (novo modelo, API, funding grande). "
    "5-7 = interessante p/ digest. 0-4 = descarte (contratações, tutoriais genéricos, marketing vazio)."
)

SYSTEM_SUMMARIZER = (
    "Você é um assistente que resume notícias de tecnologia em PORTUGUÊS (pt-AO simples e direto). "
    "Se o texto estiver em inglês, traduza o sentido, não palavra por palavra. "
    "Seja conciso. Nunca invente links. "
    "REGRA DE FORMATO (obrigatória): responda SOMENTE com os bullets e a linha final. "
    "NÃO escreva cabeçalhos, títulos ou introduções. NÃO use *, **, #, >, crases ou qualquer markdown."
)


def _get_client() -> Groq:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não definida. Copie .env.example para .env")
    return Groq(api_key=config.GROQ_API_KEY)


def _chat(messages, model: str, temperature: float = 0.3, max_tokens: int = 800) -> str:
    """Chama Groq com fallback de modelo (versatile foi descontinuado em 08/2026)."""
    client = _get_client()
    models = [model, config.GROQ_FALLBACK_MODEL]
    last_err = None
    for m in dict.fromkeys(models):  # dedup mantendo ordem
        try:
            resp = client.chat.completions.create(
                messages=messages,
                model=m,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # ex: model_decommissioned
            last_err = e
            log.warning("Groq falhou com modelo %s: %s. Tentando fallback...", m, e)
    raise RuntimeError(f"Groq falhou em todos os modelos: {last_err}")


def classify(title: str, snippet: str, source: str) -> dict:
    """Retorna {score, categoria, motivo}. Em falha, score neutro 5."""
    user = f"Fonte: {source}\nTítulo: {title}\nResumo: {snippet[:1500]}"
    try:
        raw = _chat(
            [
                {"role": "system", "content": SYSTEM_CLASSIFIER},
                {"role": "user", "content": user},
            ],
            model=config.GROQ_MODEL,
            temperature=0.1,
            max_tokens=300,
        )
        # remove cercas de código se o modelo desobedecer
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        return {
            "score": int(data.get("score", 5)),
            "categoria": str(data.get("categoria", "Técnico")),
            "motivo": str(data.get("motivo", "")),
        }
    except Exception as e:
        log.warning("classify fallback (erro=%s)", e)
        return {"score": 5, "categoria": "Técnico", "motivo": "fallback"}


def summarize_pt(title: str, content: str, article_url: str, categoria: str) -> str:
    """Resume em PT em 3 bullets + 'Por que importa'. NÃO inclui link (link é montado no processor)."""
    prompt = f"""Resuma a notícia de IA abaixo em PORTUGUÊS em exatamente 3 bullets, cada um começando com "• ".
Depois adicione uma última linha exatamente no formato "Por que importa: ..." (1 frase).
PROIBIDO: cabeçalhos, títulos, introduções, asteriscos, markdown, hashtags, crases.
Categoria: {categoria}. Tom direto, sem hype.
Título: {title}
Texto: {content[:4000]}
URL (só referência, não reescreva): {article_url}
"""
    try:
        return _chat(
            [
                {"role": "system", "content": SYSTEM_SUMMARIZER},
                {"role": "user", "content": prompt},
            ],
            model=config.GROQ_MODEL,
            temperature=0.4,
            max_tokens=600,
        ).strip()
    except Exception as e:
        log.error("summarize falhou: %s", e)
        return f"• {title}\nPor que importa: ver artigo oficial."
