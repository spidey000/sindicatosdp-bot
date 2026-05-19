# Panel de control web

El proyecto incluye un panel FastAPI **mobile-first** para administrar el bot de X detrás de Caddy Auth.

## Funciones principales

- Dashboard con estado del bot, secretos censurados y últimas ejecuciones.
- Filtros configurables para encontrar candidatos: keywords, temas, cuentas preferidas, cuentas bloqueadas, palabras excluidas y frases excluidas.
- Cola de candidatos encontrados.
- Revisión manual de cada respuesta propuesta.
- Edición, aprobación o rechazo de candidatos.
- Editor de prompts.
- Límites y modo seguro.
- Scheduler pausable.
- Logs y auditoría.
- Estado de secretos sin exponer valores reales.

## Regla de seguridad más importante

El bot **no publica nada** salvo que se cumplan todas estas condiciones:

1. El candidato está en estado `approved`.
2. `reply.manual_approval_required` está activo.
3. `reply.dry_run` está desactivado.
4. `reply.auto_reply_enabled` está activo.
5. `GETXAPI_KEY` y `X_AUTH_TOKEN` están configurados.

Por defecto el proyecto arranca con `dry_run=true`, `manual_approval_required=true` y `auto_reply_enabled=false`.

## Pantallas

### `/`

Dashboard principal: pendientes, aprobadas, errores, estado del worker, secretos y últimos candidatos.

### `/cola`

Cola de candidatos. Filtros: `pending`, `approved`, `published`, `rejected`, `error`, `all`.

### `/candidatos/{id}`

Detalle de candidato. Permite leer el tweet original, ver motivos, editar respuesta, aprobar, rechazar y consultar auditoría.

### `/filtros`

Editor de búsqueda: `keywords`, `topics`, `preferred_accounts`, `blocked_accounts`, `excluded_words`, `excluded_phrases`, `required_any_terms` y `account_query_terms`.

### `/prompts`

Editor de prompts en `config/prompts/`: `system_prompt.md`, `filtro_relevancia.md`, `respuesta_estilo.md` y `safety.md`.

### `/limites`

Configura límites diarios y seguridad de publicación.

### `/scheduler`

Activa/desactiva scheduler, cambia intervalo, pausa/reanuda y ejecuta una búsqueda manual.

### `/logs`

Muestra auditoría y últimas líneas de `logs/actividad.log`.

### `/secretos`

Muestra solo estado censurado. Los tokens y cookies nunca se muestran completos.

## API interna

Rutas útiles para automatizaciones y agentes IA detrás de Caddy Auth:

```text
GET  /api/status
GET  /api/config
PUT  /api/config
GET  /api/candidates?status=pending
GET  /api/candidates/{id}
GET  /api/secrets/status
GET  /api/logs
```

Descriptor extendido para agentes: [`PANEL_AGENT_DESCRIPTOR.md`](PANEL_AGENT_DESCRIPTOR.md).

## Archivos principales

```text
web/app.py                  servidor FastAPI y rutas
web/db.py                   SQLite, candidatos y auditoría
web/templates/              pantallas HTML mobile-first
web/static/app.css          estilos responsive
scripts/config_loader.py    carga/guarda configuración segura
scripts/search_tweets.py    búsqueda configurable en GetXAPI
scripts/run_bot.py          worker/scheduler y publicación aprobada
config/bot_config.json      configuración central
config/prompts/             prompts editables
data/bot.sqlite             base de datos local
```
