"""Jerarquía de excepciones del dominio."""

__all__ = [
    "ConfigError",
    "HistoryError",
    "NotifyError",
    "PriceDetectiveError",
    "SourceError",
    "SourceFetchError",
    "SourceParseError",
]


class PriceDetectiveError(Exception):
    """Base de todos los errores propios del proyecto."""


class SourceError(PriceDetectiveError):
    """Fallo al obtener o interpretar una fuente de precios."""


class SourceFetchError(SourceError):
    """Fallo de red o respuesta HTTP de error al consultar una fuente."""


class SourceParseError(SourceError):
    """La respuesta de una fuente no tiene la estructura esperada."""


class NotifyError(PriceDetectiveError):
    """Fallo al enviar una notificación."""


class HistoryError(PriceDetectiveError):
    """Histórico ilegible o con un formato inválido."""


class ConfigError(PriceDetectiveError):
    """Configuración de entorno ausente o inválida."""
