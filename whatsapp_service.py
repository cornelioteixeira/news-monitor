"""Wrapper Neonize (sync) com sessão persistente SQLite."""
import logging
import threading

import config

log = logging.getLogger(__name__)

_client = None
_thread: threading.Thread | None = None
_lock = threading.RLock()  # reentrante: start_in_background() chama get_client() com o lock já preso
_thread: threading.Thread | None = None


def _build_jid(phone: str):
    digits = "".join(c for c in phone if c.isdigit())
    try:
        from neonize.client import build_jid

        return build_jid(digits)
    except Exception:
        return f"{digits}@s.whatsapp.net"


def get_client():
    """Lazy singleton via ClientFactory (neonize>=0.4). O connect() na 1ª vez exibe QR no terminal."""
    global _client
    with _lock:
        if _client is not None:
            return _client
        try:
            from neonize.client import ClientFactory
        except ImportError as e:
            raise RuntimeError("neonize não instalado. Rode: pip install -r requirements.txt") from e
        factory = ClientFactory(config.WHATSAPP_DB)
        # uuid funciona como id estável da sessão (antes era o `name`)
        try:
            _client = factory.new_client(uuid=config.WHATSAPP_NAME)
        except TypeError:
            _client = factory.new_client()
        return _client


def connect():
    """Versão bloqueante (para scripts manuais): o QR aparece no terminal.

    ATENÇÃO: na API neonize>=0.4 o connect() é o loop principal — só retorna
    com Stop/Ctrl+C ou timeout de login. No FastAPI use start_in_background().
    """
    client = get_client()
    if getattr(client, "is_connected", False):
        log.info("Neonize já conectado")
        return
    client.connect()
    log.info("Neonize conectado (sessão em %s)", config.WHATSAPP_DB)


def start_in_background() -> bool:
    """Sobe o loop do Neonize numa thread daemon (não bloqueia o startup).

    1ª execução: o QR é impresso no terminal — escaneie em
    WhatsApp > Dispositivos conectados. A sessão persiste em WHATSAPP_DB,
    nas próximas execuções o login é automático. Idempotente.
    """
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        client = get_client()

        def _run():
            try:
                client.connect()
            except Exception as e:
                log.warning("Neonize loop terminou: %s", e)

        _thread = threading.Thread(target=_run, name="neonize-loop", daemon=True)
        _thread.start()
        log.info("Neonize loop iniciado em background (sessão em %s)", config.WHATSAPP_DB)
        return True


def status() -> dict:
    """Estado atual sem bloquear: conexão, login e thread do loop."""
    try:
        client = get_client()
        thread_alive = _thread is not None and _thread.is_alive()
        return {
            "connected": bool(getattr(client, "is_connected", False)),
            "logged_in": bool(getattr(client, "is_logged_in", False)),
            "loop_alive": thread_alive,
            "db": config.WHATSAPP_DB,
        }
    except Exception as e:
        return {"connected": False, "logged_in": False, "loop_alive": False, "error": str(e)}


def pair_code(phone: str | None = None) -> str:
    """Gera código de pareamento de 8 dígitos (alternativa ao QR).

    O loop precisa estar rodando — esta função o inicia se necessário.
    No celular: WhatsApp > Dispositivos conectados > Conectar com número de
    telefone, e digite o código retornado.
    """
    digits = "".join(c for c in (phone or config.MY_PHONE) if c.isdigit())
    if not digits:
        raise ValueError("Telefone inválido para pareamento")
    start_in_background()
    client = get_client()
    return client.PairPhone(digits, True)


def stop(timeout: float = 10.0) -> None:
    """Para o loop do Neonize (cancela o contexto Go) e aguarda a thread."""
    global _thread
    client = None
    with _lock:
        client = _client
        thread = _thread
    if client is not None:
        try:
            client.stop()
        except Exception as e:
            log.warning("Neonize stop: %s", e)
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
    with _lock:
        _thread = None


def send_text(text: str, phone: str | None = None) -> bool:
    """Envia texto para o seu próprio JID, com link preview (mostra o artigo oficial)."""
    phone = phone or config.MY_PHONE
    jid = _build_jid(phone)
    client = get_client()
    try:
        client.send_message(jid, text, link_preview=True)
        log.info("WhatsApp enviado para %s (%d chars)", phone, len(text))
        return True
    except Exception as e:
        log.error("Falha ao enviar WhatsApp: %s", e)
        return False


def disconnect():
    stop()
    global _client
    if _client:
        try:
            _client.disconnect()
        except Exception:
            pass
