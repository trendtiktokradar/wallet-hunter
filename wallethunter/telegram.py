"""Envío a Telegram. Sin TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID solo se registra en el log (modo prueba)."""
import logging, urllib.parse
from .config import secret
from .net import request

log = logging.getLogger("wh")


def send(text):
    tok, chat = secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        log.info("[telegram desactivado] %s", text.replace("\n", " | "))
        return False
    try:
        request(f"https://api.telegram.org/bot{tok}/sendMessage", method="POST",
                body={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, source="telegram", retries=3)
        return True
    except Exception as e:
        log.warning("Telegram falló: %s", e)
        return False
