"""Envío de mensajes por la Bot API de Telegram."""

import httpx

from price_detective.config import Settings
from price_detective.errors import NotifyError

__all__ = ["MAX_MESSAGE_LEN", "TelegramNotifier", "split_text"]

MAX_MESSAGE_LEN = 4096
_API_BASE = "https://api.telegram.org"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def split_text(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Divide `text` en partes de a lo sumo `limit` caracteres, cortando por líneas.

    Una línea más larga que el límite se corta en duro como último recurso.
    """
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


class TelegramNotifier:
    """Envía mensajes HTML al chat configurado; nunca expone el token."""

    def __init__(self, client: httpx.Client, settings: Settings) -> None:
        self._client = client
        self._chat_id = settings.telegram_chat_id
        self._url = f"{_API_BASE}/bot{settings.telegram_token}/sendMessage"

    def __repr__(self) -> str:
        return f"TelegramNotifier(chat_id={self._chat_id!r})"

    def send(self, text: str) -> None:
        """Envía `text` (HTML); lanza `NotifyError` si Telegram o la red fallan."""
        for part in split_text(text):
            self._post(part)

    def _post(self, text: str) -> None:
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        try:
            response = self._client.post(self._url, json=payload, timeout=_TIMEOUT)
        except httpx.TimeoutException:
            # `from None`: la excepción de httpx puede arrastrar la URL con el token.
            raise NotifyError("timeout al enviar el mensaje a Telegram") from None
        except httpx.HTTPError as exc:
            raise NotifyError(
                f"error de red ({type(exc).__name__}) al enviar a Telegram"
            ) from None
        if not response.is_success:
            raise NotifyError(f"Telegram respondió HTTP {response.status_code}")
