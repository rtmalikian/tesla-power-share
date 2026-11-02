# API Proposal: Fleet API discharge (V2L/V2H) endpoints

**Status: PROPOSAL — Tesla exposes none of these endpoints today.** Cybertruck
Powershare exists as hardware with no public API; Model 3/Y/S/X expose no
vehicle-to-load discharge at all. This document specifies the minimal surface
Tesla would need to ship for Tesla Power Share (and any third-party app) to
control discharge safely. Until then, this app previews these commands and
executes them only against its simulator.

## Design principles

1. **Reserve floor is server-enforced, not app-enforced.** The car must refuse
   any discharge that would take SoC below the owner's reserve, even if an app
   bugs out or is compromised. Apps set the floor; the vehicle guarantees it.
2. **Discharge is opt-in per session, with a power cap.** No standing "always
   discharge" mode: each session has an explicit start, a kW cap, and a reserve.
3. **Grid-safety first.** Discharge must stop automatically on grid restoration
   (for V2H backup-panel installs), on cable disconnect, and on any pack fault.
4. **No wakes to measure.** Discharge state must be readable from the last
   known vehicle state without waking the car; starting/stopping are the only
   wake-worthy commands.

## Proposed endpoints

All under the existing Fleet API command pattern:
`POST /api/1/vehicles/{vehicle_id}/command/<name>` with a JSON body, plus
vehicle-data fields.

### `discharge_start`

```json
{ "reserve_soc_percent": 20, "max_power_kw": 7.6, "load_profile": "home_backup" }
```

- Starts discharging to the connected home/load. `load_profile` is advisory
  (`home_backup` | `v2l_outlet` | `event`).
- Response: `{ "result": true, "discharge_state": "discharging",
  "power_kw": 6.4, "reserve_soc_percent": 20 }`.
- Must fail (not silently clamp) if the car is not connected to a
  discharge-capable outlet/panel, or if current SoC ≤ reserve.

### `discharge_stop`

```json
{}
```

- Stops discharge immediately; the car returns to its normal state.
- Idempotent: stopping an already-stopped car succeeds.

### `discharge_set_power`

```json
{ "max_power_kw": 5.0 }
```

- Adjusts the live session cap (0 < kW ≤ the panel/outlet limit, hard-capped
  by the vehicle at 11.5 kW for home installs). Out-of-range values fail.

### `discharge_set_reserve`

```json
{ "reserve_soc_percent": 30 }
```

- Adjusts the session floor (0–80%). Raising the floor above current SoC
  stops discharge immediately; lowering it never resumes a stopped session
  without an explicit `discharge_start`.

## Proposed vehicle-data fields

Under `charge_state` (or a new `discharge_state` object):

```json
{
  "discharge_state": {
    "discharging": true,
    "power_kw": 6.4,
    "reserve_soc_percent": 20,
    "max_power_kw": 7.6,
    "energy_delivered_kwh": 12.3,
    "connected_load": "home_backup"
  }
}
```

## Proposed scopes

- `vehicle_device_data` (read discharge state) — already exists for data.
- New command scope: `vehicle_discharge` — required for all four commands,
  separate from `vehicle_charging_cmds` so owners grant discharge control
  deliberately.

## Safety requirements for Tesla

- Hardware interlock: discharge only when a certified V2H panel or V2L
  adapter is connected; never energize an unconnected outlet.
- Automatic stop on grid restoration for V2H, on over-temperature, and when
  SoC reaches the reserve — with the stop reason reported in vehicle data.
- Audit: every discharge session (start/stop, kWh delivered, reserve) logged
  in the vehicle data history, as charge sessions are today.

## What this app does until these land

- Plans, previews, and simulates discharge with the exact same command names
  and validation rules (`power.py: ALLOWED_COMMANDS`, `validate_command`).
- Live mode reads SoC via existing vehicle data and prints the plan; it
  sends no discharge command, because there is no endpoint to send it to.
- The day these endpoints ship, the only change needed is wiring
  `TeslaClient.command()` calls for the four names — the planner, the AI
  service, the allowlist, and the simulator already match this spec.
