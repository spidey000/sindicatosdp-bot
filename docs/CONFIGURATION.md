# ⚙️ CONFIGURATION.md — Configuración del bot

> Cómo configurar keywords, límites, temas y personalidad del bot @sindicatosdpMAD.

---

## 1. Keywords de búsqueda

### 1.1. Grupos temáticos (orden de prioridad)

El bot busca tweets en 5 grupos de keywords, por orden de prioridad:

| # | Grupo | Query |
|---|-------|-------|
| 1 | **Huelgas** | `(huelga AND (aeropuerto OR controladores OR handling OR Barajas OR Aena)) lang:es -is:retweet` |
| 2 | **Trabajadores** | `(trabajadores AND (aeropuerto OR aviación OR handling OR Aena)) lang:es -is:retweet` |
| 3 | **Empresas del sector** | `(SAERCO OR USCAnet OR controladores OR Aena) (huelga OR trabajadores OR sindicato) lang:es -is:retweet` |
| 4 | **Jurisprudencia** | `(STC OR STS OR sentencia OR "Tribunal Constitucional") (huelga OR "servicios mínimos") lang:es -is:retweet` |
| 5 | **Actualidad aeropuerto** | `(Barajas OR "Madrid-Barajas" OR Aena OR "aeropuerto Madrid") lang:es -is:retweet` |

### 1.2. Cómo modificar las keywords

Para cambiar las keywords de búsqueda por defecto, edita la variable `query` en `scripts/search_tweets.py`:

```python
# Busca esta línea (aprox línea 65-70):
query = "..."
```

O pásalas como argumento:

```bash
python3 scripts/search_tweets.py --query "(tus nuevos términos) lang:es"
```

### 1.3. Filtros fijos

Todas las búsquedas aplican estos filtros automáticamente:

| Filtro | Valor | Propósito |
|--------|-------|-----------|
| Idioma | `lang:es` | Solo tweets en español |
| Retweets | `-is:retweet` | Solo contenido original |
| Resultados | máximo 20 | Para no saturar el análisis |

---

## 2. Límites diarios

### 2.1. Parámetros configurables

Los límites se almacenan en `config/limites.json`:

```json
{
  "fecha": "2026-05-18",
  "busquedas_realizadas": 0,
  "respuestas_enviadas": 0,
  "max_busquedas_dia": 20,
  "max_respuestas_dia": 10,
  "max_respuestas_ejecucion": 3,
  "max_por_usuario_dia": 1,
  "historial_usuarios": {},
  "ultima_ejecucion": null
}
```

| Parámetro | Valor por defecto | Descripción |
|-----------|:-----------------:|-------------|
| `max_busquedas_dia` | 20 | Máximo de búsquedas en X por día |
| `max_respuestas_dia` | 10 | Máximo de respuestas publicadas por día |
| `max_respuestas_ejecucion` | 3 | Máximo por cada ejecución del cronjob |
| `max_por_usuario_dia` | 1 | Máximo de respuestas al mismo usuario por día |

### 2.2. Cómo modificar los límites

Edita `config/limites.json` directamente:

```bash
nano config/limites.json
# Cambia los valores de max_busquedas_dia, max_respuestas_dia, etc.
```

### 2.3. Reinicio automático

Los contadores se reinician automáticamente al cambiar la fecha (día nuevo → contadores a 0).

---

## 3. Cuentas monitorizadas

El bot monitoriza tweets de estas cuentas clave (busca hasta 5 tweets por cuenta):

| Cuenta | Perfil |
|--------|--------|
| @USCAnet | Sindicato USCA (controladores) |
| @controladores | Colectivo controladores |
| @SAERCO_ANS | Empresa de handling |
| @aena | Gestor aeroportuario |
| @hosteltur | Noticias turismo |
| @transportesgob | Ministerio de Transportes |
| @instrabajoyss | Ministerio de Trabajo |
| @JulenBollain | Analista laboral |
| @javierglezv | Periodista |
| @FSCdeCCOO | CCOO sector aéreo |
| @aereoccoo | CCOO aviación |

Para modificar las cuentas, edita la lista `CUENTAS_CLAVE` en `scripts/search_tweets.py`.

---

## 4. Temas de interés (para el filtrado LLM)

El agente (LLM) filtra tweets según estas temáticas. Prioriza tweets sobre:

### Prioridad alta
- **Derecho de huelga** — servicios mínimos, vulneraciones
- **Condiciones laborales** — sueldos, horarios, turnos, descansos
- **Seguridad en plataforma** — incidentes, protocolos, equipamiento

### Prioridad media
- **Aena y gestión aeroportuaria** — decisiones, cambios organizativos
- **Handling y operativa** — empresas de handling, coordinación
- **Sindicatos y derechos laborales** — negociación colectiva, convenios

### Prioridad baja
- **Aeropuerto Madrid-Barajas** — noticias, obras, expansión
- **Aviation laboral en España** — contexto nacional del sector

---

## 5. Estilos de respuesta

| # | Estilo | % de uso | Cuándo usarlo |
|---|--------|:--------:|---------------|
| 1 | **Apoyo** | 36% | Compañero que expresa queja o preocupación |
| 2 | **Reivindicativo** | 26% | Debate sobre derechos laborales |
| 3 | **Opinión** | 14% | Compartir noticia con comentario propio |
| 4 | **Jurídico natural** | 8% | Compartir jurisprudencia sin citar números |
| 5 | **Denuncia** | 3% | Señalar situación injusta de empresas |

### 5.1. Reglas de estilo (NO negociables)

- ❌ **No usar hashtags** — 0 en 99 tweets reales
- ❌ **No usar emojis** — a menos que el original los tenga
- ❌ **No entrar en política partidista**
- ❌ **No compartir información no verificada**
- ❌ **No responder a bots o spam**
- ❌ **No sonar a ChatGPT o asistente virtual**
- ❌ **No soltar la chapa de quién eres cada dos por tres** — no eres el protagonista

---

## 6. Variables de entorno

| Variable | Obligatoria | Descripción |
|----------|:-----------:|-------------|
| `GETXAPI_KEY` | ✅ (búsquedas) | API key de GetXAPI |
| `X_AUTH_TOKEN` | ✅ (respuestas) | Cookie auth_token de x.com |
| `X_USERNAME` | ❌ | Nombre de usuario (por defecto: sindicatosdpMAD) |
| `GETXAPI_BASE_URL` | ❌ | URL base de la API |
