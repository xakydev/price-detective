"""Contrato común de las fuentes de precios y utilidad de red compartida."""

from typing import Protocol

import httpx

from price_detective.errors import SourceFetchError
from price_detective.models import Offer

__all__ = ["CONNECT_TIMEOUT_S", "TOTAL_TIMEOUT_S", "PriceSource", "get"]

CONNECT_TIMEOUT_S = 5.0
TOTAL_TIMEOUT_S = 10.0
_TIMEOUT = httpx.Timeout(TOTAL_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}


class PriceSource(Protocol):
    """Fuente de precios: devuelve ofertas ya normalizadas."""

    name: str

    def fetch(self, client: httpx.Client) -> list[Offer]:
        """Consulta la fuente; lanza `SourceError` si falla."""
        ...


def get(client: httpx.Client, url: str) -> str:
    """GET con timeouts explícitos; los fallos salen como `SourceFetchError`."""
    try:
        response = client.get(
            url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
        )
    except httpx.TimeoutException as exc:
        raise SourceFetchError(f"timeout al consultar {url}") from exc
    except httpx.HTTPError as exc:
        raise SourceFetchError(
            f"error de red ({type(exc).__name__}) al consultar {url}"
        ) from exc
    if response.status_code >= 400:
        raise SourceFetchError(f"HTTP {response.status_code} al consultar {url}")
    return response.text
