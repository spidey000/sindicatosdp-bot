#!/usr/bin/env python3
"""Carga, valida y guarda configuración central de forma segura.

Este módulo es la fuente común para scripts, worker y panel web. Nunca devuelve
secretos completos para la interfaz: solo estado censurado mediante
``get_secret_status``.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"


DEFAULT_CONFIG: dict[str, Any] = {
    "search": {
        "enabled": True,
        "language": "es",
        "include_retweets": False,
        "max_results_per_query": 20,
        "max_account_results": 5,
        "default_product": "Latest",
        "keywords": [
            "huelga",
            "servicios mínimos",
            "trabajadores",
            "derecho de huelga",
            "sindicato",
            "SAERCO",
            "aena",
            "controladores",
            "handling",
            "plataforma",
        ],
        "topics": [
            {
                "name": "Derecho de huelga",
                "priority": "high",
                "terms": ["huelga", "servicios mínimos", "derecho de huelga"],
            },
            {
                "name": "Condiciones laborales",
                "priority": "high",
                "terms": ["turnos", "descansos", "salarios", "jornada"],
            },
            {
                "name": "Sector aeroportuario",
                "priority": "medium",
                "terms": ["Aena", "Barajas", "handling", "controladores"],
            },
        ],
        "preferred_accounts": [
            "USCAnet",
            "controladores",
            "SAERCO_ANS",
            "aena",
            "hosteltur",
            "transportesgob",
            "instrabajoyss",
            "FSCdeCCOO",
            "aereoccoo",
        ],
        "blocked_accounts": [],
        "excluded_words": ["sorteo", "crypto", "apuesta", "onlyfans"],
        "excluded_phrases": [],
        "required_any_terms": [],
        "account_query_terms": ["huelga", "sindicato", "trabajadores", "laboral", "derechos"],
    },
    "reply": {
        "dry_run": True,
        "manual_approval_required": True,
        "auto_reply_enabled": False,
    },
    "scheduler": {"enabled": True, "interval_minutes": 60, "run_on_startup": False},
    "ui": {"timezone": "Europe/Madrid"},
    "web": {"require_proxy_auth_header": False, "remote_user_header": "REMOTE_USER"},
}


def _load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(fallback)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return deep_merge(deepcopy(fallback), data if isinstance(data, dict) else {})
    except Exception:
        return deepcopy(fallback)


def load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Mezcla recursiva para no perder defaults anidados."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config() -> dict[str, Any]:
    load_env_file()
    config = _load_json(CONFIG_DIR / "bot_config.json", DEFAULT_CONFIG)
    limits = _load_json(CONFIG_DIR / "limites.json", {})
    return {"config": config, "limits": limits}


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normaliza configuración recibida desde la UI.

    Lanza ValueError si hay valores peligrosos o inválidos. La validación se
    mantiene simple para no añadir dependencias extra.
    """
    cfg = deep_merge(deepcopy(DEFAULT_CONFIG), config)
    search = cfg.setdefault("search", {})
    scheduler = cfg.setdefault("scheduler", {})

    def _list(name: str) -> list[Any]:
        value = search.get(name, [])
        if isinstance(value, str):
            value = [x.strip() for x in value.replace("\n", ",").split(",") if x.strip()]
        if not isinstance(value, list):
            raise ValueError(f"search.{name} debe ser una lista")
        return value

    for field in [
        "keywords",
        "preferred_accounts",
        "blocked_accounts",
        "excluded_words",
        "excluded_phrases",
        "required_any_terms",
    ]:
        search[field] = _list(field)

    max_results = int(search.get("max_results_per_query", 20))
    if not 1 <= max_results <= 100:
        raise ValueError("max_results_per_query debe estar entre 1 y 100")
    search["max_results_per_query"] = max_results

    max_account = int(search.get("max_account_results", 5))
    if not 1 <= max_account <= 50:
        raise ValueError("max_account_results debe estar entre 1 y 50")
    search["max_account_results"] = max_account

    interval = int(scheduler.get("interval_minutes", 60))
    if interval < 5:
        raise ValueError("interval_minutes debe ser >= 5")
    scheduler["interval_minutes"] = interval

    # Parseo estricto de booleanos desde config files para que "false" no sea True
    def _strict_bool(val: Any, default: bool) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in {"1", "true", "yes", "on"}
        if isinstance(val, (int, float)):
            return val != 0
        return default

    reply = cfg.setdefault("reply", {})
    reply["manual_approval_required"] = _strict_bool(reply.get("manual_approval_required"), True)
    reply["dry_run"] = _strict_bool(reply.get("dry_run"), True)
    reply["auto_reply_enabled"] = _strict_bool(reply.get("auto_reply_enabled"), False)
    return cfg


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir = CONFIG_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"{path.stem}-{stamp}{path.suffix}"
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    cfg = validate_config(config)
    path = CONFIG_DIR / "bot_config.json"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    backup_file(path)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg


def save_limits(limits: dict[str, Any]) -> dict[str, Any]:
    path = CONFIG_DIR / "limites.json"
    backup_file(path)
    path.write_text(json.dumps(limits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return limits


def load_prompts() -> dict[str, str]:
    prompts_dir = CONFIG_DIR / "prompts"
    result: dict[str, str] = {}
    for name in ["system_prompt", "filtro_relevancia", "respuesta_estilo", "safety"]:
        path = prompts_dir / f"{name}.md"
        result[name] = path.read_text(encoding="utf-8") if path.exists() else ""
    return result


def save_prompt(name: str, content: str) -> None:
    if name not in {"system_prompt", "filtro_relevancia", "respuesta_estilo", "safety"}:
        raise ValueError("prompt no permitido")
    if not content.strip():
        raise ValueError("el prompt no puede estar vacío")
    prompts_dir = CONFIG_DIR / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    path = prompts_dir / f"{name}.md"
    backup_file(path)
    path.write_text(content, encoding="utf-8")


def get_secret_status() -> dict[str, dict[str, Any]]:
    load_env_file()
    base_url = os.environ.get("GETXAPI_BASE_URL", "https://api.getxapi.com")
    username = os.environ.get("X_USERNAME", "sindicatosdpMAD")
    return {
        "GETXAPI_KEY": {"configured": bool(os.environ.get("GETXAPI_KEY")), "value": "********" if os.environ.get("GETXAPI_KEY") else ""},
        "X_AUTH_TOKEN": {"configured": bool(os.environ.get("X_AUTH_TOKEN")), "value": "********" if os.environ.get("X_AUTH_TOKEN") else ""},
        "GETXAPI_BASE_URL": {"configured": bool(base_url), "value": base_url},
        "X_USERNAME": {"configured": bool(username), "value": username},
    }
