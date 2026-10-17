"""Configuración leída del entorno."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from price_detective.errors import ConfigError
from price_detective.models import PhoneModel

__all__ = ["DEFAULT_SUMMARY_HOURS", "LAUNCH_REFERENCE_PRICES", "Settings"]

DEFAULT_SUMMARY_HOURS = "9,21"

# Precios de lanzamiento para modelos que Apple ES ya no vende. Son una
# constante, no una variable de entorno (cifra pendiente de confirmar).
LAUNCH_REFERENCE_PRICES: Mapping[PhoneModel, Decimal] = {
    PhoneModel.IPHONE_17_PRO: Decimal("1319.00"),
}


def _parse_hours(raw: str) -> tuple[int, ...]:
    hours: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part.isascii() or not part.isdigit() or not 0 <= int(part) <= 23:
            raise ConfigError(
                f"SUMMARY_HOURS inválido: {raw!r} "
                "(se esperan horas 0-23 separadas por comas, p. ej. '9,21')"
            )
        hours.add(int(part))
    return tuple(sorted(hours))


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"Falta la variable de entorno {name}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Ajustes de una ejecución."""

    telegram_token: str = field(repr=False)
    telegram_chat_id: str
    summary_hours: tuple[int, ...]
    reference_prices: Mapping[PhoneModel, Decimal] = field(
        default_factory=lambda: dict(LAUNCH_REFERENCE_PRICES)
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Lee y valida el entorno; lanza `ConfigError` si es inválido."""
        source = os.environ if env is None else env
        token = _require(source, "TELEGRAM_BOT_TOKEN")
        chat_id = _require(source, "TELEGRAM_CHAT_ID")
        raw_hours = source.get("SUMMARY_HOURS", "").strip() or DEFAULT_SUMMARY_HOURS
        return cls(
            telegram_token=token,
            telegram_chat_id=chat_id,
            summary_hours=_parse_hours(raw_hours),
        )
