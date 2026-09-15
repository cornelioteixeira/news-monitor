"""FastAPI backend: trigger + BackgroundTasks + APScheduler (4x/dia WAT)."""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI

import config
import processor
import whatsapp_service
from feeds import FEEDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("news-ai")

scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)


def _parse_hours(s: str) -> str:
    parts = [p.strip() for p in s.split(",") if p.strip().isdigit()]
    return ",".join(parts) or "8,13,19,23"


@scheduler.scheduled_job(
    CronTrigger(hour=_parse_hours(config.DIGEST_HOURS), minute=0),
    id="digest_job",
    name="Digest IA 4x/dia",
    max_instances=1,
    coalesce=True,
)
async def scheduled_digest():
    log.info("Scheduler disparou digest")
    processor.process_all_news()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # O loop do Neonize roda em thread daemon (não bloqueia o startup).
    # 1ª execução: o QR aparece no terminal — escaneie em
    # WhatsApp > Dispositivos conectados (ou use POST /whatsapp/pair-code).
    whatsapp_service.start_in_background()
    if not scheduler.running:
        scheduler.start()
        log.info("Scheduler ativo: horas=%s tz=%s", config.DIGEST_HOURS, config.TIMEZONE)
    yield
    scheduler.shutdown(wait=False)
    whatsapp_service.stop()


app = FastAPI(title="News AI Dev Agent", lifespan=lifespan)


@app.get("/health")
def health():
    jobs = [{"id": j.id, "next": str(j.next_run_time)} for j in scheduler.get_jobs()]
    st = whatsapp_service.status()
    return {"status": "ok", "scheduler": scheduler.running, "whatsapp_ok": st.get("connected", False), "jobs": jobs}


@app.get("/whatsapp/status")
def whatsapp_status():
    """Estado da sessão WhatsApp sem bloquear."""
    return whatsapp_service.status()


@app.post("/whatsapp/pair-code")
def whatsapp_pair_code(body: dict | None = None):
    """Gera código de 8 dígitos p/ parear sem escanear QR.

    Body opcional: {"phone": "244955324708"} (default: MY_PHONE do .env).
    No celular: Dispositivos conectados > Conectar com número de telefone.
    """
    phone = (body or {}).get("phone") or config.MY_PHONE
    try:
        code = whatsapp_service.pair_code(phone)
        return {"pair_code": code, "phone": phone, "onde_usar": "WhatsApp > Dispositivos conectados > Conectar com número"}
    except Exception as e:
        return {"error": str(e), "phone": phone}


@app.post("/whatsapp/send")
def whatsapp_send(body: dict):
    """Envia texto via o cliente conectado do server. Body: {"text": "...", "phone": opcional}."""
    text = (body or {}).get("text", "")
    if not text.strip():
        return {"error": "text vazio"}
    phone = (body or {}).get("phone") or config.MY_PHONE
    ok = whatsapp_service.send_text(text, phone)
    return {"enviado": ok, "chars": len(text)}


@app.get("/feeds")
def list_feeds():
    return {"feeds": FEEDS}


@app.post("/trigger")
async def trigger(background_tasks: BackgroundTasks):
    """Dispara coleta em background (uso do cron externo ou manual)."""
    background_tasks.add_task(processor.process_all_news)
    return {"status": "Processando notícias em background"}


@app.post("/trigger-now")
def trigger_now():
    """Força verificação imediata (bloqueante, útil p/ teste)."""
    return processor.process_all_news()


@app.post("/pause")
def pause():
    scheduler.pause()
    return {"scheduler": "pausado"}


@app.post("/resume")
def resume():
    scheduler.resume()
    return {"scheduler": "ativo"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
