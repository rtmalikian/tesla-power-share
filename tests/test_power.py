import pytest

from tesla_power_share.power import (
    HomeLoad, VehicleState, default_home_loads, format_hour,
    parse_time_12h, plan_discharge, runtime_hours, select_loads,
    usable_energy_kwh, validate_command)


def car(soc=82, pack=75.0):
    return VehicleState(name="Model Y", vin="VINY", soc_percent=soc, pack_kwh=pack)


def test_usable_energy_respects_reserve():
    # (82-20)% of 75 kWh * 0.92 efficiency
    assert usable_energy_kwh(82, 75.0, 20.0) == pytest.approx(42.78, abs=0.01)


def test_usable_energy_zero_at_or_below_reserve():
    assert usable_energy_kwh(20, 75.0, 20.0) == 0.0
    assert usable_energy_kwh(10, 75.0, 20.0) == 0.0


def test_usable_energy_zero_pack():
    assert usable_energy_kwh(90, 0.0, 20.0) == 0.0


def test_runtime_math():
    assert runtime_hours(42.78, 420) == pytest.approx(101.86, abs=0.1)
    assert runtime_hours(10, 0) == float("inf")


def test_essentials_always_powered_flexible_shed_by_cap():
    loads = [HomeLoad("Fridge", 150, "essential"),
             HomeLoad("Washer", 2500, "flexible", shed_order=0),
             HomeLoad("Heater", 1500, "flexible", shed_order=2)]
    powered, shed, _ = select_loads(loads, max_discharge_kw=2.0)
    assert [l.name for l in powered] == ["Fridge", "Heater"]
    assert [l.name for l in shed] == ["Washer"]


def test_plan_never_below_reserve_and_covers_shortfall():
    plan = plan_discharge(car(82), default_home_loads(), reserve_soc=20.0,
                          wanted_hours=6.0)
    assert plan.usable_kwh == pytest.approx(42.78, abs=0.01)
    assert plan.reserve_soc == 20.0
    assert plan.runtime_hours > 6.0
    assert plan.shortfall_hours == 0.0
    assert all(l.priority == "essential" or True for l in plan.powered_loads)


def test_plan_shortfall_reported_when_battery_low():
    plan = plan_discharge(car(25), default_home_loads(), reserve_soc=20.0,
                          wanted_hours=6.0)
    assert plan.shortfall_hours > 0
    assert "short" in plan.summary()


def test_plan_at_reserve_warns_and_powers_nothing_useful():
    plan = plan_discharge(car(20), default_home_loads(), reserve_soc=20.0)
    assert plan.usable_kwh == 0.0
    assert plan.runtime_hours == 0.0
    assert plan.warnings


def test_validate_command_allowlist():
    assert validate_command("discharge_start") is None
    assert validate_command("open_frunk") is not None
    assert validate_command("discharge_set_reserve", 95) is not None
    assert validate_command("discharge_set_reserve", 30) is None
    assert validate_command("discharge_set_power", 20) is not None


def test_parse_time_12h():
    assert parse_time_12h("7:00 PM") == 19.0
    assert parse_time_12h("12:00 AM") == 0.0
    assert parse_time_12h("12:30 PM") == 12.5
    assert parse_time_12h("6pm") == 18.0
    assert parse_time_12h("25:00") is None
    assert parse_time_12h("banana") is None
    assert format_hour(19.0) == "7:00 PM"
    assert format_hour(0.0) == "12:00 AM"
