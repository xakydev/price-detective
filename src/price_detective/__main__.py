"""Entrypoint: `python -m price_detective [--force-summary]`.

Variables de entorno:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  obligatorias.
    SUMMARY_HOURS                         horas de resumen (por defecto "9,21").
    HISTORY_PATH                          ruta del histórico
                                          (por defecto ".data/history.json").
"""

import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from price_detective.app import EXIT_CONFIG_ERROR, EXIT_UNEXPECTED, run
from price_detective.config import Settings
from price_detective.errors import ConfigError

__all__ = ["DEFAULT_HISTORY_PATH", "main"]

log = logging.getLogger("price_detective")

# Donde el workflow hace checkout de la rama `data` (`path: .data`).
DEFAULT_HISTORY_PATH = ".data/history.json"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="price_detective", description="Detector de bajadas del iPhone 17."
    )
    parser.add_argument(
        "--force-summary",
        action="store_true",
        help="envía el resumen aunque no toque",
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
) -> int:
    """Lee el entorno, ejecuta una pasada y devuelve el código de salida."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # httpx registra en INFO la URL de cada petición, y la de Telegram lleva el token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _parse_args(argv)
    environ: Mapping[str, str] = os.environ if env is None else env
    try:
        settings = Settings.from_env(environ)
    except ConfigError as exc:
        log.error("Configuración inválida: %s", exc)
        return EXIT_CONFIG_ERROR

    history_path = Path(environ.get("HISTORY_PATH", "").strip() or DEFAULT_HISTORY_PATH)
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client() as client:
            return run(
                settings, client, datetime.now(UTC), args.force_summary, history_path
            )
    except Exception:  # borde de la aplicación: se registra el traceback y se sale
        log.exception("Error inesperado")
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
