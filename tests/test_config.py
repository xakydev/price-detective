from decimal import Decimal

import pytest

from price_detective.config import Settings
from price_detective.errors import ConfigError
from price_detective.models import PhoneModel


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SUMMARY_HOURS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")


class TestFromEnv:
    @pytest.mark.usefixtures("valid_env")
    def test_valid_env_builds_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUMMARY_HOURS", "8,20")
        settings = Settings.from_env()
        assert settings.telegram_token == "123:secret"
        assert settings.telegram_chat_id == "42"
        assert settings.summary_hours == (8, 20)

    @pytest.mark.usefixtures("valid_env")
    def test_missing_hours_uses_default(self) -> None:
        assert Settings.from_env().summary_hours == (9, 21)

    def test_missing_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
        with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
            Settings.from_env()

    def test_missing_chat_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret")
        with pytest.raises(ConfigError, match="TELEGRAM_CHAT_ID"):
            Settings.from_env()

    @pytest.mark.usefixtures("valid_env")
    def test_empty_hours_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUMMARY_HOURS", "")
        assert Settings.from_env().summary_hours == (9, 21)

    @pytest.mark.usefixtures("valid_env")
    def test_blank_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "   ")
        with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
            Settings.from_env()

    @pytest.mark.usefixtures("valid_env")
    @pytest.mark.parametrize("hours", ["25,abc", "25", "abc", "-1", "9,,21", "24"])
    def test_invalid_hours_raise_with_value(
        self, monkeypatch: pytest.MonkeyPatch, hours: str
    ) -> None:
        monkeypatch.setenv("SUMMARY_HOURS", hours)
        with pytest.raises(ConfigError, match="SUMMARY_HOURS"):
            Settings.from_env()

    @pytest.mark.usefixtures("valid_env")
    def test_invalid_hours_message_includes_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SUMMARY_HOURS", "25,abc")
        with pytest.raises(ConfigError, match="25,abc"):
            Settings.from_env()

    @pytest.mark.usefixtures("valid_env")
    def test_hours_are_sorted_and_deduplicated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SUMMARY_HOURS", " 21, 9,9 ")
        assert Settings.from_env().summary_hours == (9, 21)

    @pytest.mark.usefixtures("valid_env")
    def test_repr_hides_token(self) -> None:
        assert "secret" not in repr(Settings.from_env())


class TestReferencePrices:
    @pytest.mark.usefixtures("valid_env")
    def test_pro_has_fixed_launch_price(self) -> None:
        prices = Settings.from_env().reference_prices
        assert prices == {PhoneModel.IPHONE_17_PRO: Decimal("1319.00")}

    @pytest.mark.usefixtures("valid_env")
    def test_reference_prices_not_read_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REFERENCE_PRICES", "iphone-17-pro=1")
        prices = Settings.from_env().reference_prices
        assert prices[PhoneModel.IPHONE_17_PRO] == Decimal("1319.00")
