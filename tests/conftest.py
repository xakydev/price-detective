"""Fixtures compartidas: cliente HTTP simulado, HTML grabado y reloj fijo."""

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXED_NOW = datetime(2026, 10, 17, 9, 5, tzinfo=ZoneInfo("Europe/Madrid"))

Handler = Callable[[httpx.Request], httpx.Response]
ClientFactory = Callable[[Handler], httpx.Client]


@pytest.fixture
def load_fixture() -> Callable[[str], str]:
    """Devuelve el texto de un fichero de `tests/fixtures/`."""

    def _load(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture
def make_client() -> Iterator[ClientFactory]:
    """Fábrica de `httpx.Client` sobre `MockTransport`; los cierra al terminar."""
    with ExitStack() as stack:

        def _make(handler: Handler) -> httpx.Client:
            client = httpx.Client(transport=httpx.MockTransport(handler))
            return stack.enter_context(client)

        yield _make


@pytest.fixture
def now() -> datetime:
    """Instante fijo (09:05 en Europe/Madrid) para tests deterministas."""
    return FIXED_NOW


@pytest.fixture
def history_path(tmp_path: Path) -> Path:
    """Ruta de un histórico aún inexistente dentro de `tmp_path`."""
    return tmp_path / "history.json"
