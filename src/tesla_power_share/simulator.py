"""Fake fleet + fake home for demos. No API calls, no real cars.

Simulates a storm outage: the Model Y powers the home from 6:00 PM while
the grid is down, hour by hour, shedding flexible loads first and never
dropping below the reserve floor. Also runs the chat Q&A through the real
service against the fake fleet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .power import (VehicleState, default_home_loads, plan_discharge,
                    usable_energy_kwh)


@dataclass
class FakeVehicle:
    vin: str
    name: str
    soc_percent: float = 80.0
    pack_kwh: float = 75.0
    discharging: bool = False
    discharge_kw: float = 0.0
    command_log: list = field(default_factory=list)

    def state(self) -> VehicleState:
        return VehicleState(name=self.name, vin=self.vin,
                            soc_percent=self.soc_percent,
                            pack_kwh=self.pack_kwh,
                            discharging=self.discharging,
                            discharge_kw=self.discharge_kw)


def demo_vehicles() -> list[FakeVehicle]:
    return [
        FakeVehicle(vin="VINY", name="Model Y", soc_percent=82, pack_kwh=75.0),
        FakeVehicle(vin="VIN3", name="Model 3", soc_percent=47, pack_kwh=57.0),
    ]


def simulate_outage(vehicle: FakeVehicle, outage_hours: float = 6.0,
                    reserve_soc: float = 20.0,
                    max_discharge_kw: float = 7.6) -> list[str]:
    """Hour-by-hour timeline. Returns printable lines. Core invariant: the
    simulated SoC never falls below the reserve floor."""
    loads = default_home_loads()
    plan = plan_discharge(vehicle.state(), loads, reserve_soc, max_discharge_kw,
                          wanted_hours=outage_hours)
    lines = [
        f"Storm outage at Home — {vehicle.name} starts at {vehicle.soc_percent:.0f}%",
        f"Reserve floor: {reserve_soc:.0f}% — the car never goes below it.",
        f"Powering: {', '.join(l.name for l in plan.powered_loads)} "
        f"({plan.total_load_watts:.0f} W total).",
    ]
    if plan.shed_loads:
        lines.append(f"Shed to fit the {max_discharge_kw:.1f} kW cap: "
                     + ", ".join(l.name for l in plan.shed_loads) + ".")
    soc = vehicle.soc_percent
    usable = usable_energy_kwh(soc, vehicle.pack_kwh, reserve_soc)
    step = 0
    hour = 0
    while hour < outage_hours and usable > 0.001 and plan.total_load_watts > 0:
        draw = min(plan.total_load_watts / 1000.0, usable)
        usable -= draw
        soc = reserve_soc + usable / (vehicle.pack_kwh * 0.92) * 100.0
        hour += 1
        lines.append(f"  Hour {hour}: home draws {draw:.2f} kWh — "
                     f"car at {soc:.0f}% (floor {reserve_soc:.0f}%)")
        step += 1
        if step > 48:
            break
    if hour >= outage_hours:
        lines.append(f"Outage covered: all {outage_hours:.0f} hours, "
                     f"car ends at {soc:.0f}% — still above the floor.")
    else:
        lines.append(f"Home ran out of usable energy after {hour} hour(s); "
                     f"car held at its {reserve_soc:.0f}% floor — "
                     "charge or shed more loads to last longer.")
    lines.append(f"Estimated API cost: $0.00 — the simulator makes no Fleet "
                 f"API calls; a live run issues only a handful of commands "
                 f"(~$0.01–0.05/month at the default schedule).")
    return lines


DEMO_QUESTIONS = [
    "How long can my Model Y power my home?",
    "Plan for a 6-hour outage",
    "Set my reserve to 30%",
    "How long can my Model Y power my home?",
]


def run_demo(settings) -> list[tuple[str, str, list]]:
    """Run the demo Q&A through the real service against the fake fleet.
    Returns (question, answer, command_log) triples. LLM disabled."""
    from .config import VehicleConfig
    from .service import PowerShareService

    vehicles = demo_vehicles()
    settings.vehicles = [VehicleConfig(name=v.name, vin=v.vin, pack_kwh=v.pack_kwh)
                         for v in vehicles]
    states = [v.state() for v in vehicles]
    service = PowerShareService(settings, state_provider=lambda: states,
                                llm_factory=lambda: None)
    results = []
    for q in DEMO_QUESTIONS:
        body = {"model": settings.model_id,
                "messages": [{"role": "user", "content": q}]}
        resp = service.chat_completions(body)
        results.append((q, resp["choices"][0]["message"]["content"],
                        list(service.command_log)))
    return results
