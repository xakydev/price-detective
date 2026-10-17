"""Filtro de identidad: decide si un título es un iPhone 17 / 17 Pro de 256 GB nuevo."""

import re
import unicodedata

from price_detective.models import PhoneModel

__all__ = ["TARGET_STORAGE_GB", "classify"]

TARGET_STORAGE_GB = 256

_MODEL = re.compile(r"\biphone\s*17(?P<pro>\s+pro)?\b")
_CAPACITY = re.compile(r"\b(?P<amount>\d+)\s*(?P<unit>gb|tb)\b")
_DENY = re.compile(
    r"\bpro\s*max\b"
    r"|\bair\b"
    r"|\b17e\b"
    r"|\biphone\s*(?:1[0-6]|[0-9])\b"
    r"|\b(?:funda|fundas|carcasa|protector|cristal|cartera|cable|cargador)\b"
    r"|reacondicionad|renewed|refurbished|segunda\s+mano|\busado\b|seminuevo"
)


def _normalize(title: str) -> str:
    decomposed = unicodedata.normalize("NFKD", title)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def _capacities_gb(text: str) -> set[int]:
    capacities: set[int] = set()
    for match in _CAPACITY.finditer(text):
        amount = int(match["amount"])
        capacities.add(amount * 1024 if match["unit"] == "tb" else amount)
    return capacities


def classify(title: str) -> tuple[PhoneModel, int] | None:
    """Devuelve (modelo, capacidad en GB) o None si el título no es un objetivo."""
    text = _normalize(title)
    if _DENY.search(text):
        return None
    model_match = _MODEL.search(text)
    if model_match is None:
        return None
    if _capacities_gb(text) != {TARGET_STORAGE_GB}:
        return None
    model = PhoneModel.IPHONE_17_PRO if model_match["pro"] else PhoneModel.IPHONE_17
    return model, TARGET_STORAGE_GB
