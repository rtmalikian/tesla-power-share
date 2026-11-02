"""Guided first-run setup: plain-language questions, writes .env itself.

Built for Tesla owners, not developers — defaults everywhere, numbered
choices, places by name + address, times in 12-hour words, prefilled pack
sizes and reserve floor. Testable: input and output are injectable.
"""
from __future__ import annotations

import os
from pathlib import Path

from .power import DEFAULT_PACK_KWH, DEFAULT_RESERVE_SOC


def _ask(input_fn, out, prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    out(f"{prompt}{suffix}")
    answer = input_fn("> ").strip()
    return answer or default


def _ask_required(input_fn, out, prompt: str, help_text: str) -> str:
    while True:
        out(help_text)
        answer = input_fn(f"{prompt} ").strip()
        if answer:
            return answer
        out("That one's required — without it the app can't talk to your car.")


def _ask_number(input_fn, out, prompt: str, default: str) -> str:
    while True:
        answer = _ask(input_fn, out, prompt, default)
        try:
            float(answer)
            return answer
        except ValueError:
            out("That doesn't look like a number — try again, e.g. 20.")


def run_setup(input_fn=input, out=print, env_path: str = ".env") -> Path:
    out("")
    out("Welcome to Tesla Power Share setup — I'll ask a few questions and")
    out("write the settings file for you. Press Enter to accept a [default].")
    out("")

    path = Path(env_path)
    if path.exists():
        again = _ask(input_fn, out,
                     "A settings file (.env) already exists. Replace it? (y/n)", "n")
        if again.lower() not in ("y", "yes"):
            out("Keeping your existing settings. Nothing changed.")
            return path

    out("STEP 1 of 5 — Connect to Tesla")
    out("Create a free developer app at developer.tesla.com (sign in, then")
    out("'Create App'). Tesla will show you a Client ID and Client Secret.")
    client_id = _ask_required(input_fn, out, "Paste your Client ID:",
                              "First, the Client ID:")
    client_secret = _ask_required(input_fn, out, "Paste your Client Secret:",
                                  "Now the Client Secret (it stays on this computer):")

    out("")
    out("STEP 2 of 5 — Your cars")
    out("For each car: a nickname and its VIN. Find the VIN in your Tesla")
    out("app under Controls → Software (or on the car's touchscreen).")
    vehicles: list[tuple[str, str, float]] = []
    models = list(DEFAULT_PACK_KWH)
    while True:
        n = len(vehicles) + 1
        name = _ask(input_fn, out,
                    f"Car {n} nickname (e.g. Model Y) — or press Enter if done:",
                    "" if vehicles else "")
        if not name:
            if vehicles:
                break
            out("Add at least one car to continue.")
            continue
        vin = _ask_required(input_fn, out, f"VIN for {name}:",
                            f"Now the VIN for {name}:")
        out("Which model is it? (pick a number — this prefills its battery size)")
        for i, m in enumerate(models, 1):
            out(f"  {i}) {m} — about {DEFAULT_PACK_KWH[m]:.0f} kWh usable")
        out(f"  {len(models) + 1}) Something else")
        choice = _ask(input_fn, out, "Pick a number:", "2")
        try:
            idx = int(choice)
        except ValueError:
            idx = 2
        if 1 <= idx <= len(models):
            pack = DEFAULT_PACK_KWH[models[idx - 1]]
        else:
            pack = float(_ask_number(input_fn, out,
                                     "Usable battery size in kWh (e.g. 75):", "75"))
        vehicles.append((name, vin, pack))

    out("")
    out("STEP 3 of 5 — Your home")
    out("Power Share plans around one home. The address is just a label for")
    out("your plans — nothing is sent anywhere.")
    home_name = _ask(input_fn, out, "What do you call this home?", "Home")
    home_address = _ask(input_fn, out, "Street address (optional, for your plans):")

    out("")
    out("STEP 4 of 5 — The safety floor")
    out("The reserve floor is the battery your car ALWAYS keeps — it never")
    out("powers the house below this, so you can still drive to help, a")
    out("charger, or the store in an outage.")
    reserve = _ask_number(input_fn, out,
                          "Reserve floor, in percent (20 keeps about a fifth of the battery):",
                          str(int(DEFAULT_RESERVE_SOC)))
    max_kw = _ask_number(input_fn, out,
                         "Max power to the house in kW (7.6 fits a typical backup panel):",
                         "7.6")

    out("")
    out("STEP 5 of 5 — The AI brain (optional) + server")
    out("  1) Built-in answers only — no AI, nothing leaves this computer")
    out("  2) Ollama on this computer — free local AI (default)")
    out("  3) Another AI service (OpenAI, Groq, LM Studio…) — you'll paste its details")
    choice = _ask(input_fn, out, "Pick 1, 2 or 3:", "2")
    ai_mode, ai_url, ai_key, ai_model = "auto", "http://localhost:11434/v1", "", "llama3.1"
    if choice == "1":
        ai_mode = "never"
    elif choice == "3":
        ai_url = _ask_required(input_fn, out, "Service address (base URL):",
                               "Paste the service's API address:")
        ai_key = _ask(input_fn, out, "API key for that service (stored only here):")
        ai_model = _ask(input_fn, out, "Model name:", "gpt-4o-mini")

    port = _ask(input_fn, out, "Port for the chat address:", "8651")
    server_key = _ask(input_fn, out,
                      "Optional password for the chat address (blank = none):")

    lines = [
        "# Written by `tpshare setup` — edit by re-running setup any time.",
        f"TESLA_CLIENT_ID={client_id}",
        f"TESLA_CLIENT_SECRET={client_secret}",
        "TESLA_REGION=na",
        "TESLA_REDIRECT_URI=http://localhost:8080/callback",
        "TPS_VEHICLES=" + ",".join(f"{name}={vin}" for name, vin, _ in vehicles),
        "TPS_PACK_KWH=" + ",".join(f"{name}={pack:g}" for name, _, pack in vehicles),
        f"TPS_HOME_NAME={home_name}",
        f"TPS_HOME_ADDRESS={home_address}",
        f"TPS_RESERVE_SOC={reserve}",
        f"TPS_MAX_DISCHARGE_KW={max_kw}",
        "TPS_SERVER_HOST=127.0.0.1",
        f"TPS_SERVER_PORT={port}",
        f"TPS_SERVER_API_KEY={server_key}",
        "TPS_MODEL_ID=tesla-power-share",
        f"TPS_AI_BASE_URL={ai_url}",
        f"TPS_AI_API_KEY={ai_key}",
        f"TPS_AI_MODEL={ai_model}",
        f"TPS_AI_MODE={ai_mode}",
        "TPS_AI_TIMEOUT_SECONDS=20",
        "TPS_EMBEDDING_DIM=384",
        "TPS_TOKEN_FILE=~/.tps/tokens.json",
        "TPS_DRY_RUN=1",
    ]
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)

    out("")
    out("All set — settings saved to .env (only readable by you).")
    out("Next steps:")
    out("  1) tpshare auth       — sign in to Tesla once (opens a link)")
    out("  2) tpshare simulate   — see an outage demo with pretend cars")
    out("  3) tpshare preview    — see what a real discharge plan would do")
    out("  4) tpshare serve      — start the AI discharge planner")
    out("Note: Tesla doesn't expose discharge controls yet, so live commands")
    out("are previewed only — see API_PROPOSAL.md for what Tesla would need.")
    return path
