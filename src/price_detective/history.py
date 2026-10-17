"""Histórico de ofertas vistas y precios mínimos por (modelo, capacidad)."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from price_detective.errors import HistoryError
from price_detective.models import Offer

__all__ = ["MAX_SEEN_IDS", "SCHEMA_VERSION", "History", "KeyRecord", "detect_drops"]

SCHEMA_VERSION = 1
MAX_SEEN_IDS = 500


@dataclass(slots=True)
class KeyRecord:
    """Mínimo histórico e ids vistos de una clave `modelo:capacidad`."""

    min_price: Decimal
    seen_ids: list[str] = field(default_factory=list)

    def mark_seen(self, offer_id: str) -> bool:
        """Registra el id; devuelve True si era nuevo."""
        if offer_id in self.seen_ids:
            return False
        self.seen_ids.append(offer_id)
        del self.seen_ids[:-MAX_SEEN_IDS]
        return True


@dataclass(slots=True)
class History:
    """Estado persistido entre ejecuciones."""

    keys: dict[str, KeyRecord] = field(default_factory=dict)
    last_summary_slot: datetime | None = None
    # No se serializa: indica si hay algo que publicar respecto a lo cargado.
    changed: bool = field(default=False, compare=False)

    @property
    def is_empty(self) -> bool:
        return not self.keys

    def mark_summary_sent(self, slot: datetime) -> None:
        self.last_summary_slot = slot
        self.changed = True

    def to_json(self) -> str:
        data = {
            "schema_version": SCHEMA_VERSION,
            "keys": {
                key: {"min_price": str(rec.min_price), "seen_ids": rec.seen_ids}
                for key, rec in sorted(self.keys.items())
            },
            "last_summary_slot": (
                self.last_summary_slot.isoformat() if self.last_summary_slot else None
            ),
        }
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "History":
        try:
            data: Any = json.loads(text)
            return cls._from_data(data)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise HistoryError(f"Histórico inválido: {exc}") from exc

    @classmethod
    def _from_data(cls, data: Any) -> "History":
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("schema_version no soportada o estructura inesperada")
        raw_keys = data["keys"]
        if not isinstance(raw_keys, dict):
            raise TypeError("'keys' debe ser un objeto")
        keys: dict[str, KeyRecord] = {}
        for key, raw in raw_keys.items():
            seen = raw["seen_ids"]
            if not isinstance(seen, list) or not all(isinstance(i, str) for i in seen):
                raise TypeError(f"seen_ids inválido en {key!r}")
            try:
                min_price = Decimal(raw["min_price"])
            except InvalidOperation as exc:
                raise ValueError(f"min_price inválido en {key!r}") from exc
            keys[key] = KeyRecord(min_price=min_price, seen_ids=list(seen))
        raw_slot = data.get("last_summary_slot")
        slot = datetime.fromisoformat(raw_slot) if raw_slot is not None else None
        if slot is not None and slot.tzinfo is None:
            raise ValueError("last_summary_slot debe llevar zona horaria")
        return cls(keys=keys, last_summary_slot=slot)

    @classmethod
    def load(cls, path: Path) -> "History":
        """Carga el histórico; vacío si no existe, `HistoryError` si está corrupto."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls()
        except OSError as exc:
            raise HistoryError(f"No se pudo leer {path}: {exc}") from exc
        try:
            return cls.from_json(text)
        except HistoryError as exc:
            raise HistoryError(f"{path}: {exc}") from exc

    def save(self, path: Path) -> None:
        """Escribe de forma atómica (fichero temporal + replace)."""
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(self.to_json(), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            raise HistoryError(f"No se pudo guardar {path}: {exc}") from exc


def _key(offer: Offer) -> str:
    return f"{offer.model.value}:{offer.storage_gb}"


def detect_drops(history: History, offers: Sequence[Offer]) -> list[Offer]:
    """Devuelve las bajadas y actualiza el histórico (`changed` si hubo cambios).

    Con histórico vacío, o para una clave sin mínimo, la primera oferta fija la
    línea base sin alertar.
    """
    drops: list[Offer] = []
    baseline_keys: set[str] = set()
    if history.is_empty:
        baseline_keys.update(_key(offer) for offer in offers)
    for offer in offers:
        key = _key(offer)
        record = history.keys.get(key)
        if record is None:
            history.keys[key] = KeyRecord(offer.price_eur, [offer.offer_id])
            baseline_keys.add(key)
            history.changed = True
            continue
        is_new = record.mark_seen(offer.offer_id)
        if not is_new:
            continue
        history.changed = True
        if offer.price_eur < record.min_price:
            record.min_price = offer.price_eur
            if key not in baseline_keys:
                drops.append(offer)
    return drops
