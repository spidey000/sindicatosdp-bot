# 🔄 OPERATION.md — Operación diaria del bot

> Cómo opera el bot @sindicatosdpMAD, logs, monitorización y qué hacer cuando algo falla.

---

## 1. Ciclo de ejecución

El bot se ejecuta de forma automática siguiendo este ciclo:

```
CADA 60 MINUTOS
     │
     ├─ 1. Cargar configuración y credenciales
     ├─ 2. Verificar límites diarios
     ├─ 3. Buscar tweets (3 fuentes)
     ├─ 4. Analizar y filtrar (IA)
     ├─ 5. Responder (si hay candidatos)
     ├─ 6. Actualizar contadores
     └─ 7. Escribir log
```

### 1.1. Sin Hermes Agent (autónomo)

Si ejecutas el bot sin Hermes, necesitas un cron del sistema:

```bash
# Editar crontab
crontab -e

# Añadir (cada hora en punto):
0 * * * * cd /ruta/al/proyecto && python3 scripts/search_tweets.py >> logs/cron.log 2>&1
```

O con un script de shell wrapper:

```bash
#!/bin/bash
# ~/proyectos/agente-x-sindicatosdp/run_bot.sh

cd "$(dirname "$0")"
source .env 2>/dev/null || true

echo "=== $(date) ==="
python3 scripts/search_tweets.py
```

---

## 2. Logs

### 2.1. Formato del log

Los logs se almacenan en `logs/actividad.log` en formato JSON Lines (un JSON por línea):

```json
{"timestamp": "2026-05-18T14:31:30", "accion": "busqueda", "tweets_encontrados": 20, "coste": "$0.003"}
{"timestamp": "2026-05-18T14:31:35", "accion": "respuesta", "tweet_id": "1234567890", "mensaje": "ánimo compañero!", "success": true}
```

### 2.2. Ver logs

```bash
# Ver últimas líneas
tail -f logs/actividad.log

# Ver entradas de un día concreto
grep "2026-05-18" logs/actividad.log

# Contar respuestas exitosas
grep '"success": true' logs/actividad.log | wc -l
```

---

## 3. Monitorización

### 3.1. ¿Qué mirar cada día?

| Qué | Cómo | Señal de alerta |
|-----|------|-----------------|
| ¿Se ejecutó el bot? | Ver `logs/actividad.log` | Sin entradas en >2h |
| ¿Cuántas respuestas? | Contar `"accion": "respuesta"` en log | 0 respuestas en varios días → ajustar keywords |
| ¿Coste estimado? | Sumar costes en log | >$0.10/día → revisar límites |
| ¿Errores de API? | Buscar `"success": false` en log | Error 401 → renovar API key |
| ¿Token caducado? | Buscar error de auth en respuestas | Error 403/401 → renovar auth_token |

### 3.2. Dashboard rápido (sin interfaz web)

```bash
# Resumen de hoy
grep "$(date +%Y-%m-%d)" logs/actividad.log | \
  python3 -c "
import sys, json
lines = [json.loads(l) for l in sys.stdin]
busquedas = sum(1 for l in lines if l.get('accion') == 'busqueda')
respuestas = sum(1 for l in lines if l.get('accion') == 'respuesta' and l.get('success'))
errores = sum(1 for l in lines if l.get('accion') == 'respuesta' and not l.get('success'))
print(f'Búsquedas: {busquedas}')
print(f'Respuestas OK: {respuestas}')
print(f'Errores: {errores}')
"
```

---

## 4. Mantenimiento

### 4.1. Renovar auth_token de X

El `auth_token` de X caduca periódicamente. Síntomas:
- Las búsquedas funcionan ✅
- Las respuestas fallan ❌ con error 403

**Solución:**
1. Abre x.com con la cuenta del bot
2. F12 → Application → Cookies → x.com → `auth_token`
3. Copia el nuevo valor a `.env`

### 4.2. Rotación de logs

Los logs se acumulan en `logs/actividad.log`. Recomendación:

```bash
# Rotación mensual (añade al crontab)
0 0 1 * * cd /ruta/al/proyecto && mv logs/actividad.log logs/actividad-$(date +\%Y\%m).log
```

---

## 5. Resolución de problemas

### 5.1. El bot no busca tweets

```bash
# Probar conexión con GetXAPI
curl -H "Authorization: Bearer $GETXAPI_KEY" \
  "https://api.getxapi.com/twitter/tweet/advanced_search?q=test&product=Latest"
```

Si da 401 → renueva la API key en getxapi.com

### 5.2. El bot no responde

```bash
# Verificar auth_token (no vacío)
grep X_AUTH_TOKEN .env
```

Si está vacío → obtener token de cookies de x.com

### 5.3. El bot responde demasiado o muy poco

Ajusta los límites en `config/limites.json`:

| Síntoma | Ajuste |
|---------|--------|
| Responde demasiado | Bajar `max_respuestas_dia` |
| Responde muy poco | Subir `max_respuestas_ejecucion` o revisar keywords |
| Busca demasiado | Bajar `max_busquedas_dia` |
| Busca muy poco | Subir `max_busquedas_dia` |

---

## 6. Costes

| Concepto | Coste |
|----------|:-----:|
| GetXAPI búsquedas (~5/día) | ~$0.15/mes |
| GetXAPI respuestas (~3/día) | ~$0.18/mes |
| GetXAPI info usuario (~1/día) | ~$0.03/mes |
| **Total GetXAPI** | **~$0.36/mes** |
| Llamadas LLM (Hermes) | Depende de tu plan con Hermes |
