#!/usr/bin/env python3
"""
Script de búsqueda para @sindicatosdpMAD usando GetXAPI
(docs.getxapi.com).

Uso:
    python3 scripts/search_tweets.py                    # Búsqueda por defecto
    python3 scripts/search_tweets.py --mentions          # Menciones a la cuenta
    python3 scripts/search_tweets.py --query "términos"  # Búsqueda personalizada
    python3 scripts/search_tweets.py --timeline          # Timeline del usuario

Configuración:
    Copia .env.example a .env y completa las credenciales.
    O exporta las variables de entorno directamente:
        export GETXAPI_KEY=tu-key
"""

import requests
import json
import sys
import os
from datetime import datetime, timezone


def load_config():
    """Carga configuración desde .env o variables de entorno."""
    from pathlib import Path

    # Cargar .env si existe
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

    api_key = os.environ.get("GETXAPI_KEY")
    if not api_key:
        print("ERROR: GETXAPI_KEY no encontrada.", file=sys.stderr)
        print("Copia .env.example a .env y pon tu API key.", file=sys.stderr)
        sys.exit(1)

    return {
        "api_key": api_key,
        "base_url": os.environ.get("GETXAPI_BASE_URL", "https://api.getxapi.com"),
        "username": os.environ.get("X_USERNAME", "sindicatosdpMAD"),
    }


# Cuentas clave para monitorizar
CUENTAS_CLAVE = [
    "USCAnet", "controladores", "SAERCO_ANS", "aena", "hosteltur",
    "transportesgob", "instrabajoyss", "JulenBollain", "javierglezv",
    "FSCdeCCOO", "aereoccoo",
]


def search_tweets(config, query, max_results=20):
    """Busca tweets usando GetXAPI Advanced Search."""
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    params = {"q": query, "product": "Latest"}
    r = requests.get(
        f"{config['base_url']}/twitter/tweet/advanced_search",
        headers=headers,
        params=params,
    )
    if r.status_code != 200:
        return {"error": r.text[:300], "status": r.status_code}
    data = r.json()
    if "tweets" in data and len(data["tweets"]) > max_results:
        data["tweets"] = data["tweets"][:max_results]
        data["tweet_count"] = len(data["tweets"])
    return data


def get_mentions(config, max_results=20):
    """Obtiene menciones a @sindicatosdpMAD."""
    return search_tweets(config, f"to:{config['username']} lang:es", max_results)


def get_timeline(config, max_results=20):
    """Obtiene tweets del usuario."""
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    params = {"userName": config["username"]}
    r = requests.get(
        f"{config['base_url']}/twitter/user/tweets_and_replies",
        headers=headers,
        params=params,
    )
    if r.status_code != 200:
        return {"error": r.text[:300], "status": r.status_code}
    data = r.json()
    if "tweets" in data and len(data["tweets"]) > max_results:
        data["tweets"] = data["tweets"][:max_results]
    return data


def main():
    config = load_config()
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "busquedas": [],
        "getxapi_usage": {
            "cost_per_search": "$0.001",
            "cost_per_mention": "$0.001",
        },
    }

    if "--mentions" in sys.argv:
        print("🔍 Buscando menciones...", file=sys.stderr)
        data = get_mentions(config)
        results["busquedas"].append({"tipo": "mentions", "data": data})

    elif "--timeline" in sys.argv:
        print("🔍 Buscando timeline...", file=sys.stderr)
        data = get_timeline(config)
        results["busquedas"].append({"tipo": "timeline", "data": data})

    else:
        # Query por defecto basada en los 5 temas principales
        query = (
            sys.argv[sys.argv.index("--query") + 1]
            if "--query" in sys.argv
            else (
                "(huelga OR \"servicios mínimos\" OR trabajadores OR "
                "\"derecho de huelga\" OR sindicato OR SAERCO OR aena OR "
                "controladores OR handling OR plataforma) lang:es"
            )
        )
        print(f"🔍 Buscando: {query[:100]}...", file=sys.stderr)
        data = search_tweets(config, query)
        results["busquedas"].append({"tipo": "search", "query": query, "data": data})

        # Buscar tweets de cuentas clave
        for cuenta in CUENTAS_CLAVE[:3]:
            q = (
                f"from:{cuenta} "
                f"(huelga OR sindicato OR trabajadores OR laboral OR derechos) lang:es"
            )
            try:
                data = search_tweets(config, q, max_results=5)
                if "tweets" in data and data.get("tweet_count", 0) > 0:
                    results["busquedas"].append(
                        {"tipo": "from_account", "cuenta": cuenta, "data": data}
                    )
            except Exception:
                pass

    # Resumen
    total = sum(
        b.get("data", {}).get("tweet_count", 0) for b in results["busquedas"]
    )
    results["total_tweets_encontrados"] = total
    calls = len(results["busquedas"])
    results["getxapi_usage"]["total_calls"] = calls
    results["getxapi_usage"]["estimated_cost"] = f"${calls * 0.001:.3f}"

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
