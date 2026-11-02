"""CLI: tpshare setup | auth | serve | ask | plan | preview | simulate"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import ConfigError, load_settings

__version__ = "0.1.0"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")


def _client(settings):
    from .tesla_client import TeslaClient
    return TeslaClient(settings.client_id, settings.client_secret,
                       region=settings.region, redirect_uri=settings.redirect_uri,
                       token_file=settings.token_file)


def cmd_auth(args, settings) -> int:
    client = _client(settings)
    print("Open this URL in your browser and authorize:")
    print(client.authorize_url())
    print("Virtual-key pairing: https://developer.tesla.com/docs/fleet-api#pairing")
    return 0


def cmd_setup(args, settings) -> int:
    from .setup import run_setup
    run_setup()
    return 0


def _live_states(settings):
    """Live vehicle states from Fleet API (no-wake reads). If no cars are
    configured, or reads fail, explain in plain words instead of crashing."""
    from .power import VehicleState
    if not settings.vehicles:
        print("No cars configured — run `tpshare setup` first.", file=sys.stderr)
        return None
    client = _client(settings)
    states = []
    for v in settings.vehicles:
        try:
            data = client.vehicle_data(v.vin)
            soc = data.get("charge_state", {}).get("battery_level")
            if soc is None:
                print(f"Could not read {v.name}'s battery — is the car awake? "
                      "Try again when it is awake; this app never wakes a car just to measure.",
                      file=sys.stderr)
                return None
            states.append(VehicleState(name=v.name, vin=v.vin,
                                       soc_percent=float(soc),
                                       pack_kwh=v.pack_kwh))
        except Exception as exc:
            print(f"Could not read {v.name}: {exc}. Check your Tesla sign-in "
                  "(`tpshare auth`) and try again.", file=sys.stderr)
            return None
    return states


def cmd_serve(args, settings) -> int:
    from .server import serve
    from .service import PowerShareService
    states = _live_states(settings)
    if states is None:
        return 2
    service = PowerShareService(settings, state_provider=lambda: states)
    print("Vehicle data goes ONLY to your configured LLM backend "
          f"(TPS_AI_BASE_URL={settings.ai_base_url or 'none'}); "
          "the discharge planner works with no backend at all.")
    print("Note: discharge commands are PROPOSED Fleet API commands — Tesla "
          "doesn't expose them yet, so live runs preview only.")
    serve(service)
    return 0


def cmd_ask(args, settings) -> int:
    from .service import PowerShareService
    states = _live_states(settings)
    if states is None:
        return 2
    service = PowerShareService(settings, state_provider=lambda: states,
                                llm_factory=lambda: None)
    body = {"model": settings.model_id,
            "messages": [{"role": "user", "content": args.question}]}
    resp = service.chat_completions(body)
    print(resp["choices"][0]["message"]["content"])
    return 0


def cmd_plan(args, settings) -> int:
    from .power import VehicleState, default_home_loads, plan_discharge
    states = _live_states(settings)
    if states is None:
        return 2
    for v in states:
        plan = plan_discharge(v, default_home_loads(), settings.reserve_soc,
                              settings.max_discharge_kw,
                              wanted_hours=args.hours)
        print(plan.summary())
    return 0


def cmd_preview(args, settings) -> int:
    """Plain-English dry-run: what a discharge WOULD do, before anything real."""
    from .power import default_home_loads, plan_discharge
    states = _live_states(settings)
    if states is None:
        return 2
    print("PREVIEW — nothing will be sent to your car (Tesla doesn't expose")
    print("discharge controls yet; this is what the app WOULD do):")
    print("")
    for v in states:
        plan = plan_discharge(v, default_home_loads(), settings.reserve_soc,
                              settings.max_discharge_kw,
                              wanted_hours=args.hours)
        print(f"  {plan.summary()}")
        print(f"  First action would be: discharge_start on {v.name}, "
              f"capped at {settings.max_discharge_kw:.1f} kW, "
              f"stopping at {settings.reserve_soc:.0f}% battery.")
    print("")
    print("To go ahead when Tesla ships the API, re-run without --dry-run.")
    return 0


def cmd_simulate(_args, settings) -> int:
    from .simulator import demo_vehicles, run_demo, simulate_outage
    settings.dry_run = True  # preview only, even in the demo
    for line in simulate_outage(demo_vehicles()[0]):
        print(line)
    print("")
    for question, answer, log in run_demo(settings):
        print(f"> {question}")
        print(f"  {answer}")
        for cmd, vin in log:
            print(f"  [proposed fleet command, previewed] {cmd} {vin}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tpshare",
                                description="Plan how your Tesla powers your home.")
    p.add_argument("--version", action="version", version=f"tpshare {__version__}")
    p.add_argument("--env-file", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Guided first-run setup (plain-language questions)")
    sub.add_parser("auth", help="Authorize with your Tesla account (one-time)")
    sub.add_parser("serve", help="Run the OpenAI-compatible API server")
    ask_p = sub.add_parser("ask", help="One-shot question/answer (no server)")
    ask_p.add_argument("question", help="What to ask or plan")
    plan_p = sub.add_parser("plan", help="Plan discharge for your cars")
    plan_p.add_argument("--hours", type=float, default=6.0,
                        help="Outage/event length in hours (default 6)")
    prev_p = sub.add_parser("preview", help="Plain-English dry-run of a discharge plan")
    prev_p.add_argument("--hours", type=float, default=6.0)
    sub.add_parser("simulate", help="Outage demo with pretend cars (no API calls)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    env = dict(os.environ)
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True)
        env = dict(os.environ)
    else:
        from dotenv import load_dotenv
        load_dotenv(override=False)
        env = dict(os.environ)
    try:
        settings = load_settings(env)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    handlers = {"setup": cmd_setup, "auth": cmd_auth, "serve": cmd_serve,
                "ask": cmd_ask, "plan": cmd_plan, "preview": cmd_preview,
                "simulate": cmd_simulate}
    return handlers[args.command](args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
