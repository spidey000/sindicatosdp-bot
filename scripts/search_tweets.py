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
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_config():
    from scripts.config_loader import load_config as _load
    cfg = _load()["config"]
    env = {
        "api_key": os.environ.get("GETXAPI_KEY"),
        "base_url": os.environ.get("GETXAPI_BASE_URL", "https://api.getxapi.com"),
        "username": os.environ.get("X_USERNAME", "sindicatosdpMAD"),
    }
    if not env["api_key"]:
        print("ERROR: GETXAPI_KEY no encontrada.", file=sys.stderr)
        sys.exit(1)
    env["central"] = cfg
    return env


def quote_term(term: str) -> str:
    term = str(term).strip()
    return f'"{term}"' if " " in term else term


def topic_terms(topics: list[Any]) -> list[str]:
    """Extrae términos desde temas nuevos (dict) y compatibilidad con strings."""
    terms: list[str] = []
    for topic in topics or []:
        if isinstance(topic, dict):
            terms.extend(str(t).strip() for t in topic.get("terms", []) if str(t).strip())
        elif str(topic).strip():
            terms.append(str(topic).strip())
    return terms


def unique_terms(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        value = str(value).strip()
        key = value.lower()
        if value and key not in seen:
            out.append(value)
            seen.add(key)
    return out


def exclusions(central):
    search = central.get("search", {})
    parts = []
    for word in search.get("excluded_words", []):
        if str(word).strip():
            parts.append(f"-{quote_term(str(word).strip())}")
    for phrase in search.get("excluded_phrases", []):
        if str(phrase).strip():
            parts.append(f"-{quote_term(str(phrase).strip())}")
    return " ".join(parts)


def build_default_query(central):
    """Construye la query principal desde config/bot_config.json."""
    s = central.get("search", {})
    terms = unique_terms(list(s.get("keywords", [])) + topic_terms(s.get("topics", [])))
    if not terms:
        terms = ["huelga", "sindicato", "aena"]
    lang = s.get("language", "es")
    parts = ["(" + " OR ".join(quote_term(t) for t in terms) + ")", f"lang:{lang}"]
    if not s.get("include_retweets", False):
        parts.append("-is:retweet")
    exc = exclusions(central)
    if exc:
        parts.append(exc)
    return " ".join(parts)


def build_account_query(account, central):
    search = central.get("search", {})
    terms = search.get("account_query_terms", [])
    # Compatibilidad con formato antiguo {cuenta: [terms]}.
    if isinstance(terms, dict):
        terms = terms.get(account, [])
    if not terms:
        terms = search.get("keywords", [])[:4]
    lang = search.get("language", "es")
    parts = [f"from:{account}", "(" + " OR ".join(quote_term(t) for t in terms) + ")", f"lang:{lang}"]
    if not search.get("include_retweets", False):
        parts.append("-is:retweet")
    exc = exclusions(central)
    if exc:
        parts.append(exc)
    return " ".join(parts)


def tweet_username(tweet: dict[str, Any]) -> str:
    user = tweet.get("username") or tweet.get("user_name") or tweet.get("screen_name")
    if user:
        return str(user).lstrip("@")
    author = tweet.get("author") or tweet.get("user") or {}
    if isinstance(author, dict):
        return str(author.get("username") or author.get("screen_name") or author.get("name") or "").lstrip("@")
    return ""


def tweet_text(tweet: dict[str, Any]) -> str:
    return str(tweet.get("text") or tweet.get("full_text") or tweet.get("content") or "")


def local_filter(tweets, central):
    search = central.get("search", {})
    blocked = {str(a).lower().lstrip("@") for a in search.get("blocked_accounts", [])}
    excluded_words = [w.lower() for w in central.get("search", {}).get("excluded_words", [])]
    excluded_phrases = [p.lower() for p in central.get("search", {}).get("excluded_phrases", [])]
    required_any = [r.lower() for r in search.get("required_any_terms", [])]
    out = []
    for t in tweets:
        text = tweet_text(t).lower()
        user = tweet_username(t).lower()
        if user and user in blocked:
            continue
        if any(w in text for w in excluded_words):
            continue
        if any(p in text for p in excluded_phrases):
            continue
        if required_any and not any(r in text for r in required_any):
            continue
        out.append(t)
    return out


def search_tweets(config, query, max_results=20):
    """Busca tweets usando GetXAPI Advanced Search."""
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    product = config.get("central", {}).get("search", {}).get("default_product", "Latest")
    params = {"q": query, "product": product}
    r = requests.get(
        f"{config['base_url']}/twitter/tweet/advanced_search",
        headers=headers,
        params=params,
        timeout=30,
    )
    if r.status_code != 200:
        return {"error": r.text[:300], "status": r.status_code}
    data = r.json()
    if "tweets" in data:
        data["tweets"] = local_filter(data["tweets"], config.get("central", {}))
        data["tweet_count"] = len(data["tweets"])
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
        timeout=30,
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
        query = sys.argv[sys.argv.index("--query") + 1] if "--query" in sys.argv else build_default_query(config["central"])
        print(f"🔍 Buscando: {query[:100]}...", file=sys.stderr)
        max_results = config["central"].get("search", {}).get("max_results_per_query", 20)
        data = search_tweets(config, query, max_results=max_results)
        results["busquedas"].append({"tipo": "search", "query": query, "data": data})

        # Buscar tweets de cuentas clave
        max_account_results = config["central"].get("search", {}).get("max_account_results", 5)
        for cuenta in config["central"].get("search", {}).get("preferred_accounts", []):
            q = build_account_query(cuenta, config["central"])
            try:
                data = search_tweets(config, q, max_results=max_account_results)
                if "tweets" in data:
                    data["tweets"] = local_filter(data["tweets"], config["central"])
                    data["tweet_count"] = len(data["tweets"])
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
