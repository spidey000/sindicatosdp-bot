# Descriptor del panel para agentes IA

Este documento describe la estructura operativa del panel para que un agente IA pueda navegarlo, modificar configuración de forma segura y entender restricciones.

## Principio de seguridad

Nunca debe publicarse una respuesta si el candidato no está `approved`. La aprobación manual es la barrera principal.

Estados válidos de candidatos:

```text
pending     candidato creado, pendiente de revisión
edited      respuesta editada pero no aprobada
approved    aprobado manualmente para publicar
rejected    descartado
publishing  publicación en curso
published   publicado en X
error       fallo de publicación o datos inválidos
skipped     omitido por regla operativa
```

## Mapa de navegación humano

```text
/                  dashboard
/cola              lista de candidatos
/candidatos/{id}   detalle, editar, aprobar o rechazar
/filtros           configuración de búsqueda
/prompts           edición de prompts
/limites           límites y modo seguro
/scheduler         pausa, intervalo y ejecución manual
/logs              logs y auditoría
/secretos          estado censurado de secretos
```

## API JSON para agentes

Todas las rutas están detrás de Caddy Auth.

### Estado

```http
GET /api/status
```

### Configuración

```http
GET /api/config
PUT /api/config
```

La configuración principal vive en `config/bot_config.json`.

Campos importantes:

```text
search.enabled
search.language
search.include_retweets
search.max_results_per_query
search.max_account_results
search.keywords
search.topics[].name
search.topics[].priority
search.topics[].terms
search.preferred_accounts
search.blocked_accounts
search.excluded_words
search.excluded_phrases
search.required_any_terms
search.account_query_terms
reply.dry_run
reply.manual_approval_required
reply.auto_reply_enabled
scheduler.enabled
scheduler.interval_minutes
```

Al guardar configuración se crea backup automático en `config/backups/`.

### Candidatos

```http
GET /api/candidates?status=pending
GET /api/candidates/{id}
```

No existe endpoint JSON de publicación directa deliberadamente. La aprobación se hace por formulario del panel para reducir riesgo operativo.

Campos de candidato:

```text
id
tweet_id
tweet_url
username
content
source
query
status
matched_keywords
matched_topics
reply_text
edited_reply_text
approved_by
approved_at
published_at
error_message
created_at
updated_at
```

## Reglas para agentes IA

1. No solicitar ni mostrar valores completos de tokens.
2. No modificar `.env` desde el panel.
3. No desactivar `manual_approval_required`.
4. No activar publicación real sin confirmación humana explícita.
5. Preferir cambios pequeños en filtros y comprobar resultados en la cola.
6. Si hay errores de publicación, revisar `/logs` y `/secretos` antes de reintentar.
7. Mantener `dry_run=true` durante pruebas.

## Selectores conceptuales de UI

La UI no depende de un framework JS. Para automatización visual:

```text
Bottom nav: Home, Cola, Filtros, Auto, Logs
Botón ejecutar ahora: form POST /run/search
Botón aprobar: form POST /candidatos/{id}/approve
Botón rechazar: form POST /candidatos/{id}/reject
Editor filtros: form POST /filtros
Editor prompts: form POST /prompts/{name}
```

## Flujo recomendado para un agente

```text
1. GET /api/status
2. GET /api/config
3. Ajustar filtros si el humano lo pide
4. Ejecutar búsqueda manual desde /run/search o esperar scheduler
5. GET /api/candidates?status=pending
6. Resumir candidatos al humano
7. El humano aprueba/rechaza desde /candidatos/{id}
```
