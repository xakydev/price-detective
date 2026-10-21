"""Fuente Apple ES: precio oficial de lista leído del JSON de analytics."""

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx

from price_detective.config import LAUNCH_REFERENCE_PRICES
from price_detective.errors import SourceParseError
from price_detective.matching import TARGET_STORAGE_GB, classify
from price_detective.models import Offer, PhoneModel
from price_detective.sources import get

__all__ = ["IPHONE_17_URL", "AppleSource", "parse_prices"]

# Una sola petición: la tienda tiene una página por modelo y la del 17 Pro
# redirige (301) al índice desde que Apple lo retiró. Su precio sale del mapa
# de lanzamiento, no de la red.
IPHONE_17_URL = "https://www.apple.com/es/shop/buy-iphone/iphone-17"
_STORE = "Apple"
_DECODER = json.JSONDecoder(parse_float=Decimal)
_MARKER = '"products":'


def parse_prices(html: str) -> dict[PhoneModel, Decimal]:
    """Precio de 256 GB por modelo según `products[].price.fullPrice` numérico.

    El `fullPrice` textual del bloque de precios ("Desde 1.359,00 €") y el de
    otras capacidades se ignoran: se filtra por `name` con `classify`.
    """
    prices: dict[PhoneModel, Decimal] = {}
    start = html.find(_MARKER)
    while start != -1:
        begin = start + len(_MARKER)
        start = html.find(_MARKER, begin)
        try:
            products, _ = _DECODER.raw_decode(html, begin)
        except json.JSONDecodeError:
            continue
        if not isinstance(products, list):
            continue
        for product in products:
            _collect(product, prices)
    return prices


def _collect(product: Any, prices: dict[PhoneModel, Decimal]) -> None:
    if not isinstance(product, dict):
        return
    name = str(product.get("name", ""))
    classified = classify(name)
    if classified is None:
        return
    price_block = product.get("price") or {}
    if not isinstance(price_block, dict):
        raise SourceParseError(f"Apple: bloque `price` inválido en {name!r}")
    price = price_block.get("fullPrice")
    if not isinstance(price, Decimal):
        return
    if price <= 0:
        raise SourceParseError(f"Apple: precio inválido {price} en {name!r}")
    model, storage_gb = classified
    if storage_gb == TARGET_STORAGE_GB:
        prices.setdefault(model, price)


class AppleSource:
    """Referencia de precio de lista de iPhone 17 / 17 Pro 256 GB."""

    name = "apple"

    def __init__(
        self,
        reference_prices: Mapping[PhoneModel, Decimal] = LAUNCH_REFERENCE_PRICES,
    ) -> None:
        self._reference_prices = reference_prices

    def fetch(self, client: httpx.Client) -> list[Offer]:
        live = parse_prices(get(client, IPHONE_17_URL))
        offers: list[Offer] = []
        for model in PhoneModel:
            if model in live:
                offers.append(self._offer(model, live[model], launch=False))
            elif model in self._reference_prices:
                price = self._reference_prices[model]
                offers.append(self._offer(model, price, launch=True))
            else:
                raise SourceParseError(
                    f"Apple: falta el precio de {model} y no hay precio fijo"
                )
        return offers

    def _offer(self, model: PhoneModel, price: Decimal, *, launch: bool) -> Offer:
        label = "precio de lanzamiento" if launch else "precio de lista"
        return Offer(
            source=self.name,
            offer_id=f"apple:{model}",
            model=model,
            storage_gb=TARGET_STORAGE_GB,
            price_eur=price,
            title=f"{model} {TARGET_STORAGE_GB} GB ({label})",
            store=_STORE,
            url=IPHONE_17_URL,
            launch_price=launch,
        )
