#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config_loader import load_config, get_secret_status, load_prompts
from scripts.reply_tweet import reply_to_tweet
from scripts.search_tweets import (
    build_account_query,
    build_default_query,
    local_filter,
    search_tweets,
    tweet_text,
    tweet_username,
)
from web.db import init_db, get_conn, add_audit, upsert_candidate


def log_activity(entry):
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with open(os.path.join(logs_dir, "actividad.log"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def api_config_for_search(cfg):
    return {
        "api_key": os.environ.get("GETXAPI_KEY"),
        "base_url": os.environ.get("GETXAPI_BASE_URL", "https://api.getxapi.com"),
        "username": os.environ.get("X_USERNAME", "sindicatosdpMAD"),
        "central": cfg,
    }


def api_config_for_reply():
    return {
        "api_key": os.environ.get("GETXAPI_KEY"),
        "auth_token": os.environ.get("X_AUTH_TOKEN"),
        "username": os.environ.get("X_USERNAME", "sindicatosdpMAD"),
        "base_url": os.environ.get("GETXAPI_BASE_URL", "https://api.getxapi.com"),
    }


def matched_terms(text, cfg):
    lower = text.lower()
    keywords = [k for k in cfg.get("search", {}).get("keywords", []) if str(k).lower() in lower]
    topics = []
    for topic in cfg.get("search", {}).get("topics", []):
        if isinstance(topic, dict):
            terms = topic.get("terms", [])
            if any(str(t).lower() in lower for t in terms):
                topics.append(topic.get("name", "tema"))
        elif str(topic).lower() in lower:
            topics.append(str(topic))
    return keywords, topics


ALLOWED_AI_CATEGORIES = {"apoyo", "reivindicativo", "opinion", "juridico", "denuncia", "no_relevante"}


def _parse_generated_reply(raw: str) -> tuple[str, str]:
    """Parsea la respuesta estructurada del LLM.

    Formato esperado:
      CATEGORÍA: apoyo|reivindicativo|opinion|juridico|denuncia|no_relevante
      RESPUESTA: texto
    """
    category = "unknown"
    reply = ""
    category_match = re.search(r"CATEGOR[IÍ]A\s*:\s*([^\n\r]+)", raw, flags=re.IGNORECASE)
    if category_match:
        category = category_match.group(1).strip().lower().replace("í", "i")
        category = re.sub(r"[^a-z_]+", "", category)
    if category not in ALLOWED_AI_CATEGORIES:
        category = "unknown"

    reply_match = re.search(r"RESPUESTA\s*:\s*(.*)", raw, flags=re.IGNORECASE | re.DOTALL)
    if reply_match:
        reply = reply_match.group(1).strip().strip('"')
    if category == "no_relevante":
        reply = ""
    return category, reply


def generate_reply(tweet, keywords, topics) -> tuple[str, str]:
    """Genera categoría y borrador de respuesta con DeepSeek.

    Si la API falla o no está configurada, devuelve una respuesta vacía para que
    el candidato quede creado pero pendiente de edición manual.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return "unknown", ""

    text = tweet_text(tweet)
    user = tweet_username(tweet)
    prompts = load_prompts()
    system_content = "\n\n".join(
        part.strip()
        for part in [
            prompts.get("system_prompt", ""),
            prompts.get("respuesta_estilo", ""),
            prompts.get("safety", ""),
        ]
        if part and part.strip()
    )
    user_content = f"""Categoriza y genera una respuesta sugerida para este tweet.

Tweet original:
{text}

Usuario autor: @{user or 'desconocido'}
Keywords detectados: {', '.join(keywords) if keywords else 'ninguno'}
Topics detectados: {', '.join(topics) if topics else 'ninguno'}

Instrucciones de relevancia:
{prompts.get('filtro_relevancia', '').strip()}

Devuelve SOLO este formato:
CATEGORÍA: apoyo|reivindicativo|opinion|juridico|denuncia|no_relevante
RESPUESTA: texto de respuesta o vacío si no_relevante
"""
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout=30,
        )
        response = client.chat.completions.create(
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=0.55,
            max_tokens=700,
        )
        raw = response.choices[0].message.content or ""
        return _parse_generated_reply(raw)
    except Exception as exc:
        log_activity({"accion": "ai_reply_error", "resultado": str(exc)[:500]})
        return "unknown", ""


def collect_candidates(cfg):
    if not cfg.get("search", {}).get("enabled", True):
        return 0
    api_cfg = api_config_for_search(cfg)
    if not api_cfg["api_key"]:
        log_activity({"accion": "search_skipped", "resultado": "GETXAPI_KEY no configurada"})
        return 0

    searches = [("keyword_search", None, build_default_query(cfg))]
    for account in cfg.get("search", {}).get("preferred_accounts", []):
        searches.append(("preferred_account", account, build_account_query(account, cfg)))

    created = 0
    max_general = int(cfg.get("search", {}).get("max_results_per_query", 20))
    max_account = int(cfg.get("search", {}).get("max_account_results", 5))
    with get_conn() as conn:
        for source, account, query in searches:
            max_results = max_account if account else max_general
            data = search_tweets(api_cfg, query, max_results=max_results)
            tweets = local_filter(data.get("tweets", []), cfg)
            for tweet in tweets:
                tweet_id = str(tweet.get("id") or tweet.get("tweet_id") or "")
                text = tweet_text(tweet)
                username = tweet_username(tweet)
                if not tweet_id or not text:
                    continue
                keywords, topics = matched_terms(text, cfg)
                ai_category, reply_text = generate_reply(tweet, keywords, topics)
                metadata = dict(tweet)
                metadata["ai_generation"] = {"category": ai_category, "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")}
                if upsert_candidate(
                    conn,
                    tweet_id=tweet_id,
                    username=username,
                    content=text,
                    query=query,
                    source=source,
                    reply_text=reply_text,
                    metadata=metadata,
                    matched_keywords=keywords,
                    matched_topics=topics,
                ):
                    created += 1
                    add_audit(conn, None, "candidate_created", {"tweet_id": tweet_id, "source": source})
        conn.commit()
    log_activity({"accion": "busqueda_candidatos", "candidatos_creados": created, "resultado": "completed"})
    return created


def publish_approved(cfg):
    reply_cfg = cfg.get("reply", {})
    if reply_cfg.get("dry_run", True):
        log_activity({"accion": "publish_skipped", "resultado": "dry_run activo"})
        return 0
    if not reply_cfg.get("auto_reply_enabled", False):
        log_activity({"accion": "publish_skipped", "resultado": "auto_reply_enabled=false"})
        return 0
    if not reply_cfg.get("manual_approval_required", True):
        log_activity({"accion": "publish_skipped", "resultado": "manual_approval_required debe ser true"})
        return 0
    secrets = get_secret_status()
    if not (secrets["GETXAPI_KEY"]["configured"] and secrets["X_AUTH_TOKEN"]["configured"]):
        log_activity({"accion": "publish_skipped", "resultado": "secretos incompletos"})
        return 0

    limits = load_config()["limits"]
    max_respuestas_dia = int(limits.get("max_respuestas_dia", 0))
    max_respuestas_ejecucion = int(limits.get("max_respuestas_ejecucion", 0))
    max_por_usuario_dia = int(limits.get("max_por_usuario_dia", 0))

    published = 0
    with get_conn() as conn:
        while True:
            # Guard: límite por ejecución
            if max_respuestas_ejecucion > 0 and published >= max_respuestas_ejecucion:
                break
            # Guard: límite diario
            if max_respuestas_dia > 0:
                today_count = conn.execute(
                    "SELECT COUNT(*) FROM candidates WHERE status='published' AND DATE(published_at)=DATE('now')"
                ).fetchone()[0]
                if today_count >= max_respuestas_dia:
                    break
            # Claim atómico: evita doble publicación si otro worker/panel ejecuta a la vez
            row = conn.execute(
                "SELECT id, tweet_id, edited_reply_text, reply_text, username FROM candidates WHERE status='approved' ORDER BY approved_at ASC, id ASC LIMIT 1"
            ).fetchone()
            if not row:
                break
            cur = conn.execute(
                "UPDATE candidates SET status='publishing', updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='approved'",
                (row["id"],),
            )
            if cur.rowcount == 0:
                # Otro worker lo reclamó primero
                continue

            text = row["edited_reply_text"] or row["reply_text"]
            if not text:
                conn.execute("UPDATE candidates SET status='error', error_message='respuesta vacía', updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
                conn.commit()
                continue

            # Guard: límite por usuario/día
            username = row["username"] or ""
            if max_por_usuario_dia > 0 and username:
                user_count = conn.execute(
                    "SELECT COUNT(*) FROM candidates WHERE status='published' AND username=? AND DATE(published_at)=DATE('now')",
                    (username,),
                ).fetchone()[0]
                if user_count >= max_por_usuario_dia:
                    conn.execute("UPDATE candidates SET status='skipped', error_message='límite por usuario alcanzado', updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
                    conn.commit()
                    continue

            conn.commit()
            result = reply_to_tweet(api_config_for_reply(), row["tweet_id"], text)

            # Sanitizar resultado: eliminar posibles secretos antes de persistir
            safe_result = _sanitize_api_result(result)

            if result.get("success"):
                conn.execute(
                    "UPDATE candidates SET status='published', published_at=CURRENT_TIMESTAMP, publish_result=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (json.dumps(safe_result, ensure_ascii=False), row["id"]),
                )
                add_audit(conn, row["id"], "published", {"tweet_id": row["tweet_id"]})
                published += 1
            else:
                conn.execute(
                    "UPDATE candidates SET status='error', error_message=?, publish_result=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(result.get("error", "error desconocido"))[:500], json.dumps(safe_result, ensure_ascii=False), row["id"]),
                )
                add_audit(conn, row["id"], "publish_error", {"status": result.get("status")})
            conn.commit()
    log_activity({"accion": "publicar_aprobados", "publicados": published, "resultado": "completed"})
    return published


def _sanitize_api_result(result: dict) -> dict:
    """Limpia posibles secretos de respuestas API antes de persistirlas."""
    import copy
    safe = copy.deepcopy(result)
    sensitive_keys = {"auth_token", "authorization", "cookie", "x_auth_token", "api_key"}
    if isinstance(safe, dict):
        for key in list(safe.keys()):
            if key.lower() in sensitive_keys:
                safe[key] = "***"
        # También sanitizar cualquier subdict o string con formato JSON
        for key, value in list(safe.items()):
            if isinstance(value, str) and len(value) > 20:
                for sk in sensitive_keys:
                    if sk in value.lower():
                        safe[key] = "*** (sanitizado)"
                        break
    return safe


def run_once():
    cfg = load_config()["config"]
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        conn.execute("UPDATE scheduler_state SET last_run_at=?, last_status='running', updated_at=CURRENT_TIMESTAMP WHERE id=1", (now.isoformat(),))
        conn.commit()
    try:
        created = collect_candidates(cfg)
        published = publish_approved(cfg)
        interval = int(cfg.get("scheduler", {}).get("interval_minutes", 60))
        next_run = now + timedelta(minutes=interval)
        with get_conn() as conn:
            conn.execute(
                "UPDATE scheduler_state SET next_run_at=?, last_status=?, last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                (next_run.isoformat(), f"ok: {created} candidatos, {published} publicados"),
            )
            conn.commit()
    except Exception as exc:
        log_activity({"accion": "worker_error", "resultado": str(exc)[:500]})
        with get_conn() as conn:
            conn.execute("UPDATE scheduler_state SET last_status='error', last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=1", (str(exc)[:500],))
            conn.commit()
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--worker", action="store_true")
    args = p.parse_args()
    init_db()
    if args.worker:
        while True:
            cfg = load_config()["config"]
            with get_conn() as conn:
                state = conn.execute("SELECT * FROM scheduler_state WHERE id=1").fetchone()
            if cfg.get("scheduler", {}).get("enabled", True) and not (state and state["paused"]):
                run_once()
            time.sleep(max(300, int(cfg.get("scheduler", {}).get("interval_minutes", 60)) * 60))
    else:
        run_once()


if __name__ == "__main__":
    main()
