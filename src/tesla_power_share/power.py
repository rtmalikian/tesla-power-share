"""Discharge planning logic for Tesla Power Share — pure functions, no
network, no clock except an injected start hour. Fully unit-testable.

The core invariant: the car NEVER discharges below its reserve floor.
Usable energy = (SoC - reserve) * pack size * inverter efficiency, floored
at zero. Essential loads are always powered first; flexible loads are shed
(in priority order) when the load budget or the inverter cap would be
exceeded. Everything here runs deterministically with the AI backend off.

FUTURE-API note: Tesla's Fleet API exposes no discharge commands today
(Cybertruck Powershare has no public API; Model 3/Y/S/X have no V2L at
all). The command names in ALLOWED_COMMANDS are the *proposed* commands
documented in API_PROPOSAL.md; the simulator executes them against a fake
pack, and the live path only ever previews them (dry-run) until Tesla
ships the real endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Proposed Fleet API discharge commands (see API_PROPOSAL.md). The service
# validates every LLM-emitted command against this allowlist.
ALLOWED_COMMANDS = (
    "discharge_start",
    "discharge_stop",
    "discharge_set_power",
    "discharge_set_reserve",
)

# Conservative usable pack sizes (kWh) offered as wizard defaults. Owners
# can override with their car's real usable capacity.
DEFAULT_PACK_KWH = {
    "Model 3": 57.0,
    "Model Y": 75.0,
    "Model S": 95.0,
    "Model X": 95.0,
    "Cybertruck": 123.0,
}

INVERTER_EFFICIENCY = 0.92  # DC pack -> AC home conversion, conservative
DEFAULT_RESERVE_SOC = 20.0  # keep 20% in the car: enough to drive to help
DEFAULT_MAX_DISCHARGE_KW = 7.6  # typical home backup-panel limit


@dataclass
class HomeLoad:
    name: str
    watts: float
    priority: str = "essential"  # essential | flexible
    # Lower shed_order sheds first when the budget is tight.
    shed_order: int = 0


@dataclass
class VehicleState:
    name: str
    vin: str
    soc_percent: float
    pack_kwh: float = 75.0
    discharging: bool = False
    discharge_kw: float = 0.0

    def clamp(self) -> "VehicleState":
        self.soc_percent = min(100.0, max(0.0, self.soc_percent))
        return self


@dataclass
class DischargePlan:
    vehicle_name: str
    soc_percent: float
    reserve_soc: float
    usable_kwh: float
    powered_loads: list[HomeLoad] = field(default_factory=list)
    shed_loads: list[HomeLoad] = field(default_factory=list)
    total_load_watts: float = 0.0
    runtime_hours: float = 0.0
    covers_hours: float = 0.0
    shortfall_hours: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        powered = ", ".join(l.name for l in self.powered_loads) or "nothing"
        shed = ", ".join(l.name for l in self.shed_loads)
        text = (
            f"{self.vehicle_name} at {self.soc_percent:.0f}% can power {powered} "
            f"({self.total_load_watts:.0f} W) for about {self.runtime_hours:.1f} hours, "
            f"keeping {self.reserve_soc:.0f}% in reserve "
            f"({self.usable_kwh:.1f} kWh usable)."
        )
        if self.covers_hours and self.shortfall_hours > 0:
            text += (f" That covers {self.covers_hours:.1f} of the "
                     f"{self.covers_hours + self.shortfall_hours:.1f} hours you asked for"
                     f" — {self.shortfall_hours:.1f} hours short.")
        if shed:
            text += f" Shed to stay within budget: {shed}."
        if self.warnings:
            text += " " + " ".join(self.warnings)
        return text


def usable_energy_kwh(soc_percent: float, pack_kwh: float,
                      reserve_soc: float,
                      efficiency: float = INVERTER_EFFICIENCY) -> float:
    """kWh the home may draw without dropping below the reserve floor."""
    headroom = max(0.0, min(100.0, soc_percent) - max(0.0, reserve_soc))
    return headroom / 100.0 * max(0.0, pack_kwh) * efficiency


def runtime_hours(usable_kwh: float, load_watts: float) -> float:
    if load_watts <= 0:
        return float("inf")
    return usable_kwh * 1000.0 / load_watts


def select_loads(loads: list[HomeLoad], max_discharge_kw: float) -> tuple[list[HomeLoad], list[HomeLoad], list[str]]:
    """Essential loads first; shed flexible loads (lowest shed_order first)
    until total load fits the inverter cap. Returns (powered, shed, warnings)."""
    cap_w = max(0.0, max_discharge_kw) * 1000.0
    essential = [l for l in loads if l.priority == "essential"]
    flexible = sorted((l for l in loads if l.priority != "essential"),
                      key=lambda l: (l.shed_order, l.name))
    powered = list(essential)
    shed: list[HomeLoad] = []
    warnings: list[str] = []
    total = sum(l.watts for l in powered)
    if total > cap_w:
        warnings.append(
            f"Even essential loads ({total:.0f} W) exceed the {max_discharge_kw:.1f} kW "
            "discharge cap — power the essentials in turn, not all at once.")
    for load in flexible:
        if total + load.watts <= cap_w:
            powered.append(load)
            total += load.watts
        else:
            shed.append(load)
    return powered, shed, warnings


def plan_discharge(vehicle: VehicleState, loads: list[HomeLoad],
                   reserve_soc: float = DEFAULT_RESERVE_SOC,
                   max_discharge_kw: float = DEFAULT_MAX_DISCHARGE_KW,
                   wanted_hours: float = 0.0) -> DischargePlan:
    """Build the discharge plan for one vehicle. Never plans below reserve."""
    vehicle = VehicleState(**{**vehicle.__dict__}).clamp()
    reserve = min(100.0, max(0.0, reserve_soc))
    usable = usable_energy_kwh(vehicle.soc_percent, vehicle.pack_kwh, reserve)
    powered, shed, warnings = select_loads(loads, max_discharge_kw)
    total_w = sum(l.watts for l in powered)
    hours = runtime_hours(usable, total_w) if usable > 0 else 0.0
    if usable <= 0:
        warnings.append(
            f"Battery ({vehicle.soc_percent:.0f}%) is at or below the "
            f"{reserve:.0f}% reserve floor — nothing to discharge. "
            "Charge the car first, or lower the reserve floor.")
    if wanted_hours > 0:
        covers = min(hours, wanted_hours)
        shortfall = max(0.0, wanted_hours - hours)
    else:
        covers, shortfall = 0.0, 0.0
    return DischargePlan(
        vehicle_name=vehicle.name, soc_percent=vehicle.soc_percent,
        reserve_soc=reserve, usable_kwh=usable, powered_loads=powered,
        shed_loads=shed, total_load_watts=total_w, runtime_hours=hours,
        covers_hours=covers, shortfall_hours=shortfall, warnings=warnings)


def default_home_loads() -> list[HomeLoad]:
    """Typical home, prefilled in the wizard — owners edit by name."""
    return [
        HomeLoad("Fridge", 150, "essential"),
        HomeLoad("Wi-Fi + router", 30, "essential"),
        HomeLoad("Lights", 200, "essential"),
        HomeLoad("Phone chargers", 40, "essential"),
        HomeLoad("Heating / cooling", 1500, "flexible", shed_order=2),
        HomeLoad("Water heater", 2000, "flexible", shed_order=1),
        HomeLoad("Washer / dryer", 2500, "flexible", shed_order=0),
    ]


def parse_time_12h(text: str) -> float | None:
    """'7:00 PM' / '7pm' / '19:00' -> hour of day as float, or None."""
    import re
    m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([aApP][mM])?\s*$", text.strip())
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if minute > 59:
        return None
    if ampm:
        if hour < 1 or hour > 12:
            return None
        if ampm.lower() == "pm" and hour != 12:
            hour += 12
        if ampm.lower() == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        return None
    return hour + minute / 60.0


def format_hour(hour: float) -> str:
    """Hour-of-day float -> '7:00 PM' style string."""
    h = int(hour) % 24
    m = int(round((hour % 1) * 60))
    if m == 60:
        h, m = (h + 1) % 24, 0
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def validate_command(command: str, value: float | None = None) -> str | None:
    """Allowlist check for LLM-emitted discharge commands. Returns an error
    string, or None when the command is allowed (and sane)."""
    if command not in ALLOWED_COMMANDS:
        return (f"Command '{command}' is not allowed. Allowed discharge commands: "
                + ", ".join(ALLOWED_COMMANDS) + ".")
    if command == "discharge_set_reserve" and value is not None:
        if not 0 <= value <= 80:
            return "Reserve floor must be between 0% and 80% — keeping 20% is the safe default."
    if command == "discharge_set_power" and value is not None:
        if not 0 < value <= 11.5:
            return "Discharge power must be between 0 and 11.5 kW (home panel limit)."
    return None
