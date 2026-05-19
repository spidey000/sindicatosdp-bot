#!/usr/bin/env python3
"""
Responde a un tweet específico desde @sindicatosdpMAD usando GetXAPI.

Requiere X_AUTH_TOKEN en .env (cookie auth_token de x.com).

Uso:
    python3 scripts/reply_tweet.py <tweet_id> "mensaje" [@username]

Ejemplo:
    python3 scripts/reply_tweet.py 123456789 "ánimo compañero" @usuario

Configuración:
    Copia .env.example a .env y completa las credenciales.
    O exporta las variables de entorno directamente.
"""

import json
import sys
import os
import requests
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_config():
    """Carga configuración desde .env o variables de entorno."""
    from pathlib import Path

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    api_key = os.environ.get("GETXAPI_KEY")
    auth_token = os.environ.get("X_AUTH_TOKEN")
    username = os.environ.get("X_USERNAME", "sindicatosdpMAD")
    base_url = os.environ.get("GETXAPI_BASE_URL", "https://api.getxapi.com")

    if not api_key:
        print("ERROR: GETXAPI_KEY no encontrada.", file=sys.stderr)
        sys.exit(1)

    if not auth_token:
        print(
            "ERROR: X_AUTH_TOKEN no encontrado.",
            file=sys.stderr,
        )
        print(
            "Es necesario para responder tweets. "
            "Se obtiene de las cookies de x.com.",
            file=sys.stderr,
        )
        sys.exit(1)

    return {
        "api_key": api_key,
        "auth_token": auth_token,
        "username": username,
        "base_url": base_url,
    }


def reply_to_tweet(config, tweet_id, message):
    """Responde a un tweet usando GetXAPI."""
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "text": message,
        "auth_token": config["auth_token"],
        "in_reply_to_tweet_id": tweet_id,
    }
    r = requests.post(
        f"{config['base_url']}/twitter/tweet/create",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if r.status_code == 200:
        data = r.json()
        return {"success": True, "output": data}
    else:
        return {"success": False, "error": r.text[:500], "status": r.status_code}


def log_activity(config, tweet_id, message, success):
    """Registra la actividad en el log."""
    log_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "logs",
    )
    os.makedirs(log_dir, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "accion": "respuesta",
        "tweet_id": tweet_id,
        "mensaje": message[:100],
        "success": success,
    }

    log_file = os.path.join(log_dir, "actividad.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def update_counter(tweet_id, username=None):
    """Actualiza el contador de respuestas."""
    counter_file = os.path.expanduser("~/.hermes/xbot-counters.json")
    try:
        with open(counter_file, "r") as f:
            counters = json.load(f)

        today = datetime.now().strftime("%Y-%m-%d")
        if counters.get("fecha") != today:
            counters["fecha"] = today
            counters["respuestas_enviadas"] = 0
            counters["historial_usuarios"] = {}

        counters["respuestas_enviadas"] = counters.get("respuestas_enviadas", 0) + 1
        counters.setdefault("historial_usuarios", {})
        if username:
            counters["historial_usuarios"][username] = (
                counters["historial_usuarios"].get(username, 0) + 1
            )

        counters["ultima_ejecucion"] = datetime.now().isoformat()

        with open(counter_file, "w") as f:
            json.dump(counters, f, indent=2)

        return True
    except Exception as e:
        print(f"Error actualizando contador: {e}", file=sys.stderr)
        return False


def main():
    if len(sys.argv) < 3:
        print(
            f"Uso: python3 {sys.argv[0]} <tweet_id> \"mensaje\" [@username]"
        )
        sys.exit(1)

    config = load_config()
    tweet_id = sys.argv[1]
    message = sys.argv[2]
    username = sys.argv[3] if len(sys.argv) > 3 else None

    print(f"📤 Respondiendo a tweet {tweet_id}...", file=sys.stderr)

    result = reply_to_tweet(config, tweet_id, message)
    log_activity(config, tweet_id, message, result["success"])

    if result["success"]:
        update_counter(tweet_id, username)

    result["tweet_id"] = tweet_id
    result["mensaje"] = message[:100]
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
