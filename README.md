# Tesla Power Share — How Long Can Your Tesla Power Your Home? (Free V2L/V2H Outage Planner for Model 3/Y/S/X/Cybertruck)

▶ **[Try the live demo](https://rtmalikian.github.io/tesla-power-share/)** — plan an outage in your browser with pretend cars, no install, no car needed.

**Free & open source Tesla Fleet API app: plan vehicle-to-home (V2L/V2H) discharge for your Tesla — outage and event planner, reserve floor, load budget, and an OpenAI-compatible AI endpoint — with a deterministic offline fallback.**

## Why?

BYD ships vehicle-to-load (V2L) discharge across its line. Tesla offers Powershare on Cybertruck only, with **no public API** — and nothing at all for Model 3, Model Y, Model S, or Model X. Owners keep asking the same question in every storm thread: *"my car has 80% battery — how long could it actually run my house?"* No free tool answers that, and nobody plans it: which loads stay on, what gets shed, and how much battery must stay in the car so you can still drive to help.

Tesla Power Share answers it — and ships the full product now, ready the day Tesla exposes discharge controls (see `API_PROPOSAL.md`).

- **Outage/event planner**: "plan for a 6-hour outage" → usable kWh, powered vs shed loads, runtime, and shortfall — computed by a rules engine, never guessed.
- **Reserve floor, always**: the car NEVER discharges below your reserve (default 20%). That battery is for driving to a charger, a store, or help.
- **Essential loads first**: fridge, Wi-Fi, lights and chargers stay on; flexible loads (washer, water heater, HVAC) shed in order when the power cap or energy budget runs out.
- **Ask in plain language**: "how long can my Model Y power my home?" — via its own OpenAI-compatible `/v1/chat/completions` endpoint, with a pluggable LLM backend (local Ollama by default) or fully offline.
- **Preview before anything real**: `tpshare preview` prints, in plain English, exactly what a discharge would do. Live commands are previewed only until Tesla ships the API — see below.

## How it works

```
Storm outage, 6:00 PM — Model Y at 82%, reserve floor 20%
  Usable energy: (82% − 20%) × 75 kWh × 0.92 efficiency = 42.8 kWh
  Powering: Fridge, Wi-Fi + router, Lights, Phone chargers,
            Washer/dryer, Water heater, Heating/cooling (6,420 W)
  Hour 1: home draws 6.42 kWh — car at 73% (floor 20%)
  Hour 6: home draws 6.42 kWh — car at 26% (floor 20%)
  Outage covered: all 6 hours, car ends at 26% — still above the floor.
```

Expected API cost: ~$0.01–0.05/month at the default schedule — the planner issues only a handful of commands, and `simulate` makes no Fleet API calls at all. (Wakes dominate the Tesla Fleet API bill; this app never wakes a car just to measure.)

**Honest FUTURE-API note:** Tesla's Fleet API exposes no discharge commands today, and only Cybertruck has Powershare hardware. This app therefore ships the complete planner, simulator, AI service, and API proposal now. The simulator executes the proposed commands against a fake pack; the live path previews them (dry-run) and never claims to control a real car. When Tesla ships the endpoints in `API_PROPOSAL.md`, the same code paths execute for real.

## Quickstart (for owners, not developers)

```bash
git clone https://github.com/rtmalikian/tesla-power-share && cd tesla-power-share
python3 -m venv .venv && .venv/bin/pip install -e .
tpshare setup      # plain-language questions — writes .env for you
tpshare simulate   # see an outage demo with pretend cars (no Tesla account needed)
tpshare preview --hours 6   # plain-English plan for YOUR cars, nothing sent
tpshare serve      # start the AI endpoint on http://127.0.0.1:8651
```

No AI needed: the planner, the preview, and every answer above work with no LLM backend at all. Vehicle data is sent ONLY to the LLM backend you configure (default: Ollama on your own computer) — nowhere else.

## Tesla developer setup

Create an app at [developer.tesla.com](https://developer.tesla.com) (sign in → Create App), then run `tpshare setup` and paste the Client ID and Secret it shows you. Run `tpshare auth` once to sign in, and pair a virtual key per the [Fleet API pairing docs](https://developer.tesla.com/docs/fleet-api#pairing). Scopes needed: vehicle data + commands (discharge commands are proposed — see `API_PROPOSAL.md`).

## AI endpoints

```bash
curl http://127.0.0.1:8651/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "tesla-power-share",
       "messages": [{"role": "user", "content": "how long can my Model Y power my home?"}]}'

curl http://127.0.0.1:8651/v1/models
curl http://127.0.0.1:8651/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"input": "6-hour outage plan"}'
```

The model answers from computed plans (never invented numbers). If an LLM backend is configured it may emit a JSON command block, which the service validates against the discharge allowlist (`discharge_start`, `discharge_stop`, `discharge_set_power`, `discharge_set_reserve`) before accepting it — anything else is rejected. Streaming is not supported (`stream=true` is ignored). Optional bearer auth: set `TPS_SERVER_API_KEY`.

## `.env` reference

| Variable | Default | What it means |
|---|---|---|
| `TPS_VEHICLES` | — | Cars as `name=VIN` pairs (setup writes this) |
| `TPS_PACK_KWH` | by model | Usable pack size per car in kWh |
| `TPS_HOME_NAME` / `TPS_HOME_ADDRESS` | Home / — | Label for your plans |
| `TPS_RESERVE_SOC` | 20 | Battery % the car never goes below |
| `TPS_MAX_DISCHARGE_KW` | 7.6 | Max power to the house in kW |
| `TPS_SERVER_HOST` / `TPS_SERVER_PORT` | 127.0.0.1 / 8651 | The AI endpoint address |
| `TPS_SERVER_API_KEY` | — | Optional password for the endpoint |
| `TPS_AI_BASE_URL` / `TPS_AI_MODEL` / `TPS_AI_MODE` | Ollama / llama3.1 / auto | Pluggable LLM backend |
| `TPS_DRY_RUN` | 1 | 1 = preview commands, never send them |

## FAQ

**Can my Model 3/Y power my house today?**
Not through Tesla's API — no discharge endpoint exists, and only Cybertruck has Powershare hardware. This app plans for that day and simulates the full product now.

**How long will my car actually last in an outage?**
Roughly: (your battery % − reserve %) × pack size × 0.92, divided by your home's load in kW. A Model Y at 82% with a 20% reserve powers a typical 6.4 kW home load for about 6.7 hours; a light essentials-only load (~420 W) lasts over 100 hours. Run `tpshare plan --hours 12` for your numbers.

**What is the reserve floor, and why 20%?**
The battery your car keeps no matter what — so you can still drive to a charger or to help after the outage. 20% is the default; change it with `tpshare setup` or by asking "set my reserve to 30%".

**What gets shed first if power runs short?**
Flexible loads, in order: washer/dryer, then water heater, then heating/cooling. Essentials (fridge, Wi-Fi, lights, phone chargers) are never shed by the planner.

**Does it work without AI?**
Yes — the rules engine plans, answers, and previews everything with no backend. The LLM only handles free-form phrasing.

**Will it wake my car or cost much in API fees?**
No — it never wakes a car just to measure, and live runs issue only a handful of commands (~$0.01–0.05/month).

**What does Tesla need to ship for this to control a real car?**
The four endpoints in `API_PROPOSAL.md`: `discharge_start`, `discharge_stop`, `discharge_set_power`, and `discharge_set_reserve`, plus a discharge-state field in vehicle data.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q   # 38 tests
PYTHONPATH=src .venv/bin/python -m tesla_power_share.cli simulate
```

Tests cover config parsing, discharge math and edge cases (at/below reserve, zero pack, cap shedding, invalid commands), OpenAI response shapes, the HTTP server (including bearer auth), the setup wizard (scripted answers → config loads), and an end-to-end simulation asserting the core invariant: the simulated car never drops below its reserve floor.

## Keywords

Tesla Fleet API, free open source, Model 3, Model Y, Model S, Model X, Cybertruck, V2L, V2H, Powershare, vehicle-to-home, home backup, outage planning, battery backup, off-peak.

MIT License — Raphael Malikian. Part of the Tesla AI Series: one Tesla owner pain point per day, each with embedded OpenAI-compatible AI.
