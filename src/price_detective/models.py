"""Modelos de dominio: modelos de teléfono, ofertas y resultados de fuente."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from price_detective.errors import PriceDetectiveError

__all__ = ["Offer", "PhoneModel", "SourceResult"]


class PhoneModel(StrEnum):
    """Modelos de iPhone rastreados."""

    IPHONE_17 = "iphone-17"
    IPHONE_17_PRO = "iphone-17-pro"


@dataclass(frozen=True, slots=True)
class Offer:
    """Oferta normalizada de un iPhone nuevo."""

    source: str
    offer_id: str
    model: PhoneModel
    storage_gb: int
    price_eur: Decimal
    title: str
    store: str
    url: str
    # True si el precio es el fijo de lanzamiento de un modelo que Apple ya no
    # vende, no un precio vivo de la tienda.
    launch_price: bool = False

    def __post_init__(self) -> None:
        if self.price_eur <= 0:
            raise PriceDetectiveError(
                f"El precio debe ser positivo, recibido {self.price_eur}"
            )


@dataclass(frozen=True, slots=True)
class SourceResult:
    """Resultado de consultar una fuente: ofertas o el motivo del fallo."""

    source: str
    offers: tuple[Offer, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
