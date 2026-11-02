"""Configuration for Tesla Power Share. All settings come from the
environment (see .env.example). Copy .env.example to .env — .env is
git-ignored so secrets never leave your machine."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(Exception):
    pass


@dataclass
class VehicleConfig:
    name: str
    vin: str
    pack_kwh: float = 75.0


@dataclass
class Settings:
    client_id: str = ""
    client_secret: str = ""
    region: str = "na"
    redirect_uri: str = "http://localhost:8080/callback"
    token_file: str = "~/.tps/tokens.json"
    vehicles: list[VehicleConfig] = field(default_factory=list)
    # The OpenAI-compatible server this app exposes.
    server_host: str = "127.0.0.1"
    server_port: int = 8651
    server_api_key: str = ""          # optional bearer token for /v1/*
    model_id: str = "tesla-power-share"
    # Pluggable LLM backend (any OpenAI-compatible API; default: local Ollama).
    ai_base_url: str = "http://localhost:11434/v1"
    ai_api_key: str = ""
    ai_model: str = "llama3.1"
    ai_mode: str = "auto"             # auto | always | never
    ai_timeout_seconds: float = 20.0
    embedding_dim: int = 384
    dry_run: bool = False
    # Power Share discharge defaults (owner-editable via `tpshare setup`).
    reserve_soc: float = 20.0
    max_discharge_kw: float = 7.6
    home_name: str = "Home"
    home_address: str = ""


def _parse_vehicles(raw: str) -> list[VehicleConfig]:
    """Format: name=VIN,name2=VIN2 (or bare VINs)."""
    vehicles = []
    for idx, item in enumerate(raw.split(",")):
        item = item.strip()
        if not item:
            continue
        name = None
        if "=" in item:
            name, item = item.split("=", 1)
            name = name.strip()
        vin = item.strip()
        if not vin:
            raise ConfigError("Empty VIN in TPS_VEHICLES")
        vehicles.append(VehicleConfig(name=name or f"car-{idx + 1}", vin=vin))
    if not vehicles:
        raise ConfigError("TPS_VEHICLES is empty — add at least one name=VIN entry")
    return vehicles


def _int(env: dict, key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _float(env: dict, key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


def _bool(env: dict, key: str, default: bool = False) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_settings(env: dict | None = None) -> Settings:
    env = os.environ if env is None else env
    s = Settings()
    s.client_id = env.get("TESLA_CLIENT_ID", "")
    s.client_secret = env.get("TESLA_CLIENT_SECRET", "")
    s.region = env.get("TESLA_REGION", "na").strip().lower()
    if s.region not in ("na", "eu", "cn"):
        raise ConfigError(f"TESLA_REGION must be na|eu|cn, got {s.region!r}")
    s.redirect_uri = env.get("TESLA_REDIRECT_URI", s.redirect_uri)
    s.token_file = env.get("TPS_TOKEN_FILE", s.token_file)
    raw_vehicles = env.get("TPS_VEHICLES", "")
    if raw_vehicles.strip():
        s.vehicles = _parse_vehicles(raw_vehicles)
    s.server_host = env.get("TPS_SERVER_HOST", s.server_host)
    s.server_port = _int(env, "TPS_SERVER_PORT", s.server_port)
    s.server_api_key = env.get("TPS_SERVER_API_KEY", "")
    s.model_id = env.get("TPS_MODEL_ID", s.model_id)
    s.ai_base_url = env.get("TPS_AI_BASE_URL", s.ai_base_url).rstrip("/")
    s.ai_api_key = env.get("TPS_AI_API_KEY", "")
    s.ai_model = env.get("TPS_AI_MODEL", s.ai_model)
    s.ai_mode = env.get("TPS_AI_MODE", s.ai_mode).strip().lower()
    if s.ai_mode not in ("auto", "always", "never"):
        raise ConfigError(f"TPS_AI_MODE must be auto|always|never, got {s.ai_mode!r}")
    s.ai_timeout_seconds = _float(env, "TPS_AI_TIMEOUT_SECONDS", s.ai_timeout_seconds)
    s.embedding_dim = _int(env, "TPS_EMBEDDING_DIM", s.embedding_dim)
    if not (8 <= s.embedding_dim <= 4096):
        raise ConfigError("TPS_EMBEDDING_DIM must be between 8 and 4096")
    s.dry_run = _bool(env, "TPS_DRY_RUN")
    s.reserve_soc = _float(env, "TPS_RESERVE_SOC", s.reserve_soc)
    if not 0 <= s.reserve_soc <= 80:
        raise ConfigError("TPS_RESERVE_SOC must be between 0 and 80")
    s.max_discharge_kw = _float(env, "TPS_MAX_DISCHARGE_KW", s.max_discharge_kw)
    if not 0 < s.max_discharge_kw <= 11.5:
        raise ConfigError("TPS_MAX_DISCHARGE_KW must be between 0 and 11.5")
    s.home_name = env.get("TPS_HOME_NAME", s.home_name)
    s.home_address = env.get("TPS_HOME_ADDRESS", s.home_address)
    # Per-car pack sizes: TPS_PACK_KWH="Model Y=75,Model 3=57"; defaults by
    # model name, 75 kWh when unknown.
    from .power import DEFAULT_PACK_KWH
    packs: dict[str, float] = {}
    for item in env.get("TPS_PACK_KWH", "").split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            try:
                packs[k.strip()] = float(v)
            except ValueError as exc:
                raise ConfigError(f"TPS_PACK_KWH value must be a number, got {v!r}") from exc
    for v in s.vehicles:
        if v.name in packs:
            v.pack_kwh = packs[v.name]
        else:
            for model, kw in DEFAULT_PACK_KWH.items():
                if model.lower() in v.name.lower():
                    v.pack_kwh = kw
                    break
    return s
