"""Transport-independent Power Share service: OpenAI-shaped requests in,
OpenAI-shaped responses out. The HTTP server (server.py) is a thin wrapper;
tests drive this class directly.

The service works from a VehicleState provider (live Fleet reads in
production, fake states in tests/simulator) — the rules engine plans
discharge deterministically with no LLM. Discharge commands are PROPOSED
Fleet API commands (API_PROPOSAL.md): in dry-run / demo mode they are
reported, never sent to a real car, because Tesla exposes no discharge
endpoint today. The allowlist in power.py is enforced before any command
is accepted, including LLM-emitted ones.
"""
from __future__ import annotations

import itertools
import re
import time

from .embeddings import embed_text
from .llm import LlmBackend, extract_command
from .power import (ALLOWED_COMMANDS, VehicleState, default_home_loads,
                    plan_discharge, validate_command)

CAPABILITY_BLURB = (
    "I plan how long your Tesla can power your home in an outage or event, "
    "keeping a reserve floor in the car. Try: \"how long can my Model Y power "
    "my home?\", \"plan for a 6-hour outage\", \"start discharging\", or "
    "\"set my reserve to 30%\". Discharge commands are proposed Fleet API "
    "commands (Tesla doesn't expose them yet) — in this demo they are previewed, "
    "not sent to a real car."
)


class PowerShareService:
    def __init__(self, settings, state_provider=None, llm_factory=None,
                 command_log=None):
        self.settings = settings
        # state_provider() -> list[VehicleState]; default: no cars configured.
        self.state_provider = state_provider or (lambda: [])
        self.llm_factory = llm_factory
        self.command_log = command_log if command_log is not None else []
        self._ids = itertools.count(1)

    # -- plumbing ------------------------------------------------------
    def _states(self) -> list[VehicleState]:
        return self.state_provider()

    def _find(self, name: str) -> VehicleState | None:
        name = name.lower()
        for v in self._states():
            if name in v.name.lower() or v.name.lower() in name:
                return v
        return None

    def _llm(self):
        if self.llm_factory is not None:
            return self.llm_factory()
        if self.settings.ai_mode == "never":
            return None
        if not self.settings.ai_base_url:
            return None
        return LlmBackend(self.settings.ai_base_url, self.settings.ai_api_key,
                          self.settings.ai_model, self.settings.ai_timeout_seconds)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{int(time.time())}-{next(self._ids)}"

    def _brief(self) -> str:
        parts = []
        for v in self._states():
            parts.append(f"{v.name}: {v.soc_percent:.0f}% SoC, "
                         f"{v.pack_kwh:.0f} kWh pack"
                         + (", discharging" if v.discharging else ""))
        return "; ".join(parts) or "No cars configured."

    # -- rules ---------------------------------------------------------
    def _rules_answer(self, text: str) -> str | None:
        low = text.lower()
        states = self._states()
        if not states:
            return ("No cars are configured yet — run `tpshare setup` and add "
                    "at least one car first.")
        # "set reserve to 30%" / "reserve 30"
        m = re.search(r"reserve[^0-9]*(\d{1,3})\s*%", low)
        if "reserve" in low and m:
            err = validate_command("discharge_set_reserve", float(m.group(1)))
            if err:
                return err
            self.settings.reserve_soc = float(m.group(1))
            self.command_log.append(("discharge_set_reserve", m.group(1)))
            return (f"Reserve floor set to {m.group(1)}% — your car will never "
                    f"discharge below that. "
                    f"(Proposed command; previewed, not sent to a real car.)")
        if "stop discharg" in low or "stop power" in low:
            self.command_log.append(("discharge_stop", ""))
            return ("Discharge stopped (previewed — proposed Fleet API command, "
                    "not sent to a real car).")
        if "start discharg" in low or "power my home" in low and "start" in low:
            v = self._find(text) or states[0]
            plan = plan_discharge(v, default_home_loads(),
                                  self.settings.reserve_soc,
                                  self.settings.max_discharge_kw)
            self.command_log.append(("discharge_start", v.name))
            return (plan.summary() + " Discharge started in preview mode — "
                    "no real car command is sent until Tesla ships the API.")
        # Outage / runtime questions
        m = re.search(r"(\d+(?:\.\d+)?)\s*-?\s*hour", low)
        wanted = float(m.group(1)) if m else 0.0
        if any(k in low for k in ("how long", "outage", "power my home",
                                  "power the house", "run my home", "blackout",
                                  "storm", "event", "plan")):
            v = self._find(text) or states[0]
            plan = plan_discharge(v, default_home_loads(),
                                  self.settings.reserve_soc,
                                  self.settings.max_discharge_kw,
                                  wanted_hours=wanted)
            return plan.summary()
        if "what can" in low and ("power" in low or "run" in low):
            v = self._find(text) or states[0]
            plan = plan_discharge(v, default_home_loads(),
                                  self.settings.reserve_soc,
                                  self.settings.max_discharge_kw)
            return plan.summary()
        return None

    # -- OpenAI surface ------------------------------------------------
    def models_list(self) -> dict:
        return {"object": "list", "data": [{
            "id": self.settings.model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "tesla-power-share",
        }]}

    def chat_completions(self, body: dict) -> dict:
        messages = body.get("messages") or []
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = str(m.get("content") or "")
                break
        answer = self._rules_answer(user_text)
        if answer is None:
            answer = self._llm_answer(user_text)
        return {
            "id": self._next_id("chatcmpl"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.settings.model_id,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def embeddings(self, body: dict) -> dict:
        raw = body.get("input", "")
        texts = raw if isinstance(raw, list) else [raw]
        data = []
        for i, t in enumerate(texts):
            data.append({
                "object": "embedding",
                "index": i,
                "embedding": embed_text(str(t), self.settings.embedding_dim),
            })
        return {
            "object": "list",
            "data": data,
            "model": self.settings.model_id,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    def _llm_answer(self, user_text: str, ) -> str:
        llm = self._llm()
        if llm is None:
            return CAPABILITY_BLURB
        try:
            reply = llm.chat(self._brief(), user_text)
        except Exception:
            return CAPABILITY_BLURB + " (The AI backend didn't respond just now.)"
        cmd = extract_command(reply)
        if cmd is None:
            return reply
        command, vehicle_name = cmd
        err = validate_command(command)
        if err:
            return err
        vehicle = self._find(vehicle_name)
        if vehicle is None:
            return f"I couldn't match \"{vehicle_name}\" to one of your cars."
        self.command_log.append((command, vehicle.name))
        return (f"Preview: would run {command} on {vehicle.name} "
                f"(proposed Fleet API command — not sent to a real car, "
                f"because Tesla doesn't expose discharge controls yet).")
