from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scripts.config_loader import (
    BASE_DIR,
    get_secret_status,
    load_config,
    load_prompts,
    save_config,
    save_limits,
    save_prompt,
)
from web.db import add_audit, get_conn, init_db, normalize_row

app = FastAPI(title="Panel @sindicatosdpMAD", description="Panel mobile-first para gestionar el bot de X")
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")
init_db()


@app.on_event("startup")
def startup():
    init_db()


def _auth_check(request: Request):
    cfg = load_config()["config"].get("web", {})
    env_required = os.environ.get("REQUIRE_PROXY_AUTH_HEADER", "").lower() in {"1", "true", "yes"}
    if not (cfg.get("require_proxy_auth_header") or env_required):
        return
    header = cfg.get("remote_user_header", os.environ.get("REMOTE_USER_HEADER", "Remote-User"))
    if not (request.headers.get(header) or request.headers.get("X-Forwarded-User") or request.headers.get("Remote-User")):
        raise HTTPException(status_code=401, detail="proxy auth required")
    # CSRF ligero para mutaciones
    _csrf_check(request)


def _csrf_check(request: Request):
    """Protección CSRF ligera para rutas mutables detrás de Caddy Auth."""
    if request.method not in {"POST", "PUT", "DELETE", "PATCH"}:
        return
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    # Si no hay Origin/Referer, es llamada CLI/API, permitimos.
    if not origin:
        return
    # Coincidencia con Host o relativo
    host = request.headers.get("Host", "")
    if host and (host in origin or origin.startswith("/")):
        return
    # Permitir localhost/testing
    if "localhost" in origin or "127.0.0.1" in origin:
        return
    raise HTTPException(status_code=403, detail="csrf rejected")


def current_user(request: Request) -> str:
    cfg = load_config()["config"].get("web", {})
    header_name = cfg.get("remote_user_header", os.environ.get("REMOTE_USER_HEADER", "Remote-User"))
    return (
        request.headers.get(header_name)
        or request.headers.get("Remote-User")
        or request.headers.get("X-Forwarded-User")
        or request.headers.get("X-Forwarded-Email")
        or "panel"
    )


def render(request: Request, template: str, **context):
    _auth_check(request)
    context.setdefault("config", load_config()["config"])
    context.setdefault("limits", load_config()["limits"])
    context.setdefault("path", request.url.path)
    return templates.TemplateResponse(request, template, context)


def parse_lines(value: str) -> list[str]:
    items: list[str] = []
    for part in value.replace("\r", "").replace(",", "\n").split("\n"):
        part = part.strip().lstrip("@")
        if part:
            items.append(part)
    # conservar orden y quitar duplicados
    seen = set()
    out = []
    for item in items:
        key = item.lower()
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out


def form_str(form, key: str, default: str = "") -> str:
    value = form.get(key, default)
    return value if isinstance(value, str) else default


def form_int(form, key: str, default: int) -> int:
    value = form_str(form, key, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def topics_from_form(names: list[str], priorities: list[str], terms: list[str]) -> list[dict[str, Any]]:
    topics = []
    for idx, name in enumerate(names):
        name = name.strip()
        topic_terms = parse_lines(terms[idx] if idx < len(terms) else "")
        if name or topic_terms:
            topics.append(
                {
                    "name": name or ", ".join(topic_terms[:2]) or "Tema",
                    "priority": priorities[idx] if idx < len(priorities) and priorities[idx] else "medium",
                    "terms": topic_terms,
                }
            )
    return topics


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with get_conn() as conn:
        counts = {
            row["status"]: row["total"]
            for row in conn.execute("SELECT status, COUNT(*) total FROM candidates GROUP BY status").fetchall()
        }
        state = conn.execute("SELECT * FROM scheduler_state WHERE id=1").fetchone()
        latest = conn.execute("SELECT * FROM candidates ORDER BY id DESC LIMIT 5").fetchall()
    return render(
        request,
        "dashboard.html",
        title="Dashboard",
        counts=counts,
        scheduler=dict(state) if state else {},
        latest=[normalize_row(r) for r in latest],
        secrets=get_secret_status(),
    )


@app.get("/cola", response_class=HTMLResponse)
def cola(request: Request, status: str = "pending"):
    with get_conn() as conn:
        if status == "all":
            rows = conn.execute("SELECT * FROM candidates ORDER BY id DESC LIMIT 100").fetchall()
        else:
            rows = conn.execute("SELECT * FROM candidates WHERE status=? ORDER BY id DESC LIMIT 100", (status,)).fetchall()
    return render(request, "cola.html", title="Cola", candidates=[normalize_row(r) for r in rows], active_status=status)


@app.get("/candidatos/{candidate_id}", response_class=HTMLResponse)
def candidato(request: Request, candidate_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        audit = conn.execute("SELECT * FROM audit_log WHERE candidate_id=? ORDER BY id DESC", (candidate_id,)).fetchall()
    if not row:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    return render(request, "candidato.html", title="Candidato", candidate=normalize_row(row), audit=[dict(a) for a in audit])


@app.post("/candidatos/{candidate_id}/approve")
async def approve_candidate(candidate_id: int, request: Request):
    _auth_check(request)
    form = await request.form()
    reply = str(form.get("reply_text", "")).strip()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404)
        final_reply = reply or row["edited_reply_text"] or row["reply_text"]
        conn.execute(
            """
            UPDATE candidates
            SET status='approved', edited_reply_text=?, approved_by=?, approved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status IN ('pending','edited','rejected','error')
            """,
            (final_reply, current_user(request), candidate_id),
        )
        add_audit(conn, candidate_id, "approved", {"user": current_user(request)})
        conn.commit()
    return RedirectResponse(f"/candidatos/{candidate_id}", status_code=303)


@app.post("/candidatos/{candidate_id}/reject")
async def reject_candidate(candidate_id: int, request: Request):
    _auth_check(request)
    form = await request.form()
    reason = str(form.get("reason", "")).strip()
    with get_conn() as conn:
        conn.execute("UPDATE candidates SET status='rejected', error_message=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (reason, candidate_id))
        add_audit(conn, candidate_id, "rejected", {"user": current_user(request), "reason": reason})
        conn.commit()
    return RedirectResponse("/cola?status=pending", status_code=303)


@app.post("/candidatos/{candidate_id}/edit")
async def edit_candidate(candidate_id: int, request: Request):
    _auth_check(request)
    form = await request.form()
    reply = str(form.get("reply_text", "")).strip()
    if not reply:
        raise HTTPException(status_code=400, detail="La respuesta no puede estar vacía")
    with get_conn() as conn:
        conn.execute("UPDATE candidates SET status='edited', edited_reply_text=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (reply, candidate_id))
        add_audit(conn, candidate_id, "edited", {"user": current_user(request)})
        conn.commit()
    return RedirectResponse(f"/candidatos/{candidate_id}", status_code=303)


@app.get("/filtros", response_class=HTMLResponse)
def filtros(request: Request):
    return render(request, "filtros.html", title="Filtros")


@app.post("/filtros")
async def save_filters(request: Request):
    _auth_check(request)
    form = await request.form()
    cfg = load_config()["config"]
    search = cfg.setdefault("search", {})
    search["enabled"] = form.get("enabled") == "on"
    search["language"] = form_str(form, "language", "es") or "es"
    search["include_retweets"] = form.get("include_retweets") == "on"
    search["max_results_per_query"] = form_int(form, "max_results_per_query", 20)
    search["max_account_results"] = form_int(form, "max_account_results", 5)
    search["default_product"] = form_str(form, "default_product", "Latest") or "Latest"
    search["keywords"] = parse_lines(form_str(form, "keywords"))
    search["preferred_accounts"] = parse_lines(form_str(form, "preferred_accounts"))
    search["blocked_accounts"] = parse_lines(form_str(form, "blocked_accounts"))
    search["excluded_words"] = parse_lines(form_str(form, "excluded_words"))
    search["excluded_phrases"] = parse_lines(form_str(form, "excluded_phrases"))
    search["required_any_terms"] = parse_lines(form_str(form, "required_any_terms"))
    search["account_query_terms"] = parse_lines(form_str(form, "account_query_terms"))
    search["topics"] = topics_from_form(
        [str(x) for x in form.getlist("topic_name")],
        [str(x) for x in form.getlist("topic_priority")],
        [str(x) for x in form.getlist("topic_terms")],
    )
    save_config(cfg)
    return RedirectResponse("/filtros?saved=1", status_code=303)


@app.get("/prompts", response_class=HTMLResponse)
def prompts(request: Request):
    return render(request, "prompts.html", title="Prompts", prompts=load_prompts())


@app.post("/prompts/{name}")
async def save_prompt_route(name: str, request: Request):
    _auth_check(request)
    form = await request.form()
    save_prompt(name, str(form.get("content", "")))
    return RedirectResponse("/prompts?saved=1", status_code=303)


@app.get("/limites", response_class=HTMLResponse)
def limites(request: Request):
    return render(request, "limites.html", title="Límites")


@app.post("/limites")
async def save_limits_route(request: Request):
    _auth_check(request)
    form = await request.form()
    limits = load_config()["limits"]
    for key in ["max_busquedas_dia", "max_respuestas_dia", "max_respuestas_ejecucion", "max_por_usuario_dia"]:
        limits[key] = form_int(form, key, int(limits.get(key, 0)))
    save_limits(limits)

    cfg = load_config()["config"]
    reply = cfg.setdefault("reply", {})
    reply["dry_run"] = form.get("dry_run") == "on"
    reply["manual_approval_required"] = form.get("manual_approval_required") == "on"
    reply["auto_reply_enabled"] = form.get("auto_reply_enabled") == "on"
    reply["max_tweet_age_days"] = form_int(form, "max_tweet_age_days", int(reply.get("max_tweet_age_days", 7)))
    save_config(cfg)
    return RedirectResponse("/limites?saved=1", status_code=303)


@app.get("/scheduler", response_class=HTMLResponse)
def scheduler(request: Request):
    with get_conn() as conn:
        state = conn.execute("SELECT * FROM scheduler_state WHERE id=1").fetchone()
    return render(request, "scheduler.html", title="Scheduler", scheduler=dict(state) if state else {})


@app.post("/scheduler")
async def save_scheduler(request: Request):
    _auth_check(request)
    form = await request.form()
    cfg = load_config()["config"]
    scheduler_cfg = cfg.setdefault("scheduler", {})
    scheduler_cfg["enabled"] = form.get("enabled") == "on"
    scheduler_cfg["interval_minutes"] = form_int(form, "interval_minutes", 60)
    scheduler_cfg["run_on_startup"] = form.get("run_on_startup") == "on"
    save_config(cfg)
    return RedirectResponse("/scheduler?saved=1", status_code=303)


@app.post("/scheduler/pause")
def pause_scheduler(request: Request):
    _auth_check(request)
    with get_conn() as conn:
        conn.execute("UPDATE scheduler_state SET paused=1, updated_at=CURRENT_TIMESTAMP WHERE id=1")
        conn.commit()
    return RedirectResponse("/scheduler", status_code=303)


@app.post("/scheduler/resume")
def resume_scheduler(request: Request):
    _auth_check(request)
    with get_conn() as conn:
        conn.execute("UPDATE scheduler_state SET paused=0, updated_at=CURRENT_TIMESTAMP WHERE id=1")
        conn.commit()
    return RedirectResponse("/scheduler", status_code=303)


@app.post("/run/search")
def run_search_now(request: Request):
    """Ejecuta búsqueda de candidatos. NO publica aprobados."""
    _auth_check(request)
    from scripts.run_bot import collect_candidates
    from scripts.config_loader import load_config

    cfg = load_config()["config"]
    collect_candidates(cfg)
    return RedirectResponse("/cola?status=pending", status_code=303)


@app.post("/run/publish")
def run_publish_now(request: Request):
    """Publica candidatos aprobados. Solo funciona si dry_run=false y auto_reply_enabled=true."""
    _auth_check(request)
    from scripts.run_bot import publish_approved
    from scripts.config_loader import load_config

    cfg = load_config()["config"]
    published = publish_approved(cfg)
    return RedirectResponse(f"/cola?status={'published' if published else 'approved'}", status_code=303)


@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request):
    log_path = BASE_DIR / "logs" / "actividad.log"
    lines = []
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    with get_conn() as conn:
        audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100").fetchall()
    return render(request, "logs.html", title="Logs", log_lines=list(reversed(lines)), audit=[dict(a) for a in audit])


@app.get("/secretos", response_class=HTMLResponse)
def secretos(request: Request):
    return render(request, "secretos.html", title="Secretos", secrets=get_secret_status())


@app.get("/docs/panel", response_class=PlainTextResponse)
def panel_descriptor(request: Request):
    _auth_check(request)
    descriptor = BASE_DIR / "docs" / "PANEL_AGENT_DESCRIPTOR.md"
    return descriptor.read_text(encoding="utf-8") if descriptor.exists() else "Descriptor no disponible"


# API JSON para agentes IA o automatizaciones internas detrás de Caddy Auth.
@app.get("/api/status")
def api_status(request: Request):
    _auth_check(request)
    with get_conn() as conn:
        counts = {row["status"]: row["total"] for row in conn.execute("SELECT status, COUNT(*) total FROM candidates GROUP BY status")}
        state = conn.execute("SELECT * FROM scheduler_state WHERE id=1").fetchone()
    return {"ok": True, "secrets": get_secret_status(), "counts": counts, "scheduler": dict(state) if state else {}}


@app.get("/api/config")
def api_config(request: Request):
    _auth_check(request)
    return load_config()["config"]


@app.put("/api/config")
async def api_save_config(request: Request):
    _auth_check(request)
    body = await request.json()
    return save_config(body)


@app.get("/api/candidates")
def api_candidates(request: Request, status: str = "pending"):
    _auth_check(request)
    with get_conn() as conn:
        if status == "all":
            rows = conn.execute("SELECT * FROM candidates ORDER BY id DESC LIMIT 200").fetchall()
        else:
            rows = conn.execute("SELECT * FROM candidates WHERE status=? ORDER BY id DESC LIMIT 200", (status,)).fetchall()
    return [normalize_row(r) for r in rows]


@app.get("/api/candidates/{candidate_id}")
def api_candidate(request: Request, candidate_id: int):
    _auth_check(request)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    return normalize_row(row)


@app.get("/api/secrets/status")
def api_secrets(request: Request):
    _auth_check(request)
    return get_secret_status()


@app.get("/api/logs")
def api_logs(request: Request):
    _auth_check(request)
    log_path = BASE_DIR / "logs" / "actividad.log"
    if not log_path.exists():
        return []
    return log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
