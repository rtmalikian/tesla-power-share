import pytest

from tesla_power_share.config import ConfigError, load_settings

BASE = {"TPS_VEHICLES": "Model Y=VINY,Model 3=VIN3"}


def test_parse_vehicles_and_pack_defaults():
    s = load_settings(dict(BASE))
    assert [v.name for v in s.vehicles] == ["Model Y", "Model 3"]
    assert [v.pack_kwh for v in s.vehicles] == [75.0, 57.0]
    assert s.server_port == 8651
    assert s.ai_mode == "auto"
    assert s.ai_base_url == "http://localhost:11434/v1"
    assert s.reserve_soc == 20.0
    assert s.max_discharge_kw == 7.6


def test_pack_override():
    s = load_settings({**BASE, "TPS_PACK_KWH": "Model Y=80"})
    assert s.vehicles[0].pack_kwh == 80.0


def test_bad_region():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TESLA_REGION": "moon"})


def test_bad_ai_mode():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TPS_AI_MODE": "sometimes"})


def test_bad_reserve():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TPS_RESERVE_SOC": "95"})


def test_bad_max_kw():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TPS_MAX_DISCHARGE_KW": "20"})


def test_ai_base_trailing_slash_trimmed():
    s = load_settings({**BASE, "TPS_AI_BASE_URL": "http://x/v1/"})
    assert s.ai_base_url == "http://x/v1"


def test_dry_run_parse():
    assert load_settings({**BASE, "TPS_DRY_RUN": "1"}).dry_run is True
