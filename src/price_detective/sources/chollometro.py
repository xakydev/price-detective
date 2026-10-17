"""Fuente Chollómetro: ofertas del JSON `data-vue3` de la página de búsqueda."""

import json
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any

import httpx

from price_detective.errors import SourceParseError
from price_detective.matching import classify
from price_detective.models import Offer
from price_detective.sources import get

__all__ = ["SEARCH_URL", "ChollometroSource", "parse_offers"]

SEARCH_URL = "https://www.chollometro.com/search?q=iphone%2017&hide_expired=true"
_COMPONENT = "ThreadMainListItemNormalizer"


class _ThreadCollector(HTMLParser):
    """Recoge el `props.thread` de cada bloque `ThreadMainListItemNormalizer`."""

    def __init__(self) -> None:
        super().__init__()
        self.threads: list[dict[str, Any]] = []
        self.articles = 0  # artículos de oferta presentes en el HTML
        self.payloads = 0  # atributos data-vue3 con JSON válido

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article" and (dict(attrs).get("id") or "").startswith("thread_"):
            self.articles += 1
        for key, value in attrs:
            if key != "data-vue3" or not value:
                continue
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                continue
            self.payloads += 1
            if isinstance(payload, dict) and payload.get("name") == _COMPONENT:
                thread = payload.get("props", {}).get("thread")
                if isinstance(thread, dict):
                    self.threads.append(thread)


def _to_offer(thread: dict[str, Any]) -> Offer | None:
    if thread.get("isExpired"):
        return None
    title = str(thread.get("title", ""))
    classified = classify(title)
    if classified is None or not thread.get("price"):
        return None
    model, storage_gb = classified
    thread_id = str(thread["threadId"])
    merchant = thread.get("merchant") or {}
    return Offer(
        source="chollometro",
        offer_id=f"chollometro:{thread_id}",
        model=model,
        storage_gb=storage_gb,
        price_eur=Decimal(str(thread["price"])),
        title=title,
        store=str(merchant.get("merchantName") or "Chollómetro"),
        url=str(thread["shareableLink"]),
    )


def parse_offers(html: str) -> list[Offer]:
    """Extrae las ofertas válidas; `SourceParseError` si no hay bloques."""
    collector = _ThreadCollector()
    collector.feed(html)
    # Un listado vacío no trae artículos pero conserva otros bloques data-vue3
    # (paginación, etiquetas). Hay artículos sin bloque reconocible, o ningún
    # data-vue3, solo si la estructura de la página cambió.
    if not collector.threads and (collector.articles or not collector.payloads):
        raise SourceParseError(
            f"Chollómetro: no se encontró ningún bloque {_COMPONENT}"
        )
    offers = (_to_offer(thread) for thread in collector.threads)
    return [offer for offer in offers if offer is not None]


class ChollometroSource:
    """Ofertas vigentes de iPhone 17 / 17 Pro 256 GB en Chollómetro."""

    name = "chollometro"

    def fetch(self, client: httpx.Client) -> list[Offer]:
        return parse_offers(get(client, SEARCH_URL))
