# 🏗️ ARCHITECTURE.md — Arquitectura del sistema

> Diseño técnico del bot @sindicatosdpMAD: componentes, flujo de datos y decisiones arquitectónicas.

---

## 1. Visión general

```
┌────────────────────────────────────────────────────────────────┐
│                    SISTEMA @sindicatosdpMAD                      │
│                                                                  │
│   ⏰ CRONJOB (cada 60 min)                                       │
│      │                                                           │
│      ├──▶ 1. Cargar configuración (.env)                        │
│      │                                                           │
│      ├──▶ 2. Verificar límites diarios (config/limites.json)    │
│      │    ├── ¿Superó búsquedas? → FIN                          │
│      │    └── ¿Superó respuestas? → FIN (solo búsquedas)        │
│      │                                                           │
│      ├──▶ 3. PIPELINE DE BÚSQUEDA                               │
│      │    ├── Búsqueda por keywords (search_tweets.py)           │
│      │    ├── Menciones (search_tweets.py --mentions)            │
│      │    └── Cuentas clave                                      │
│      │                                                           │
│      ├──▶ 4. PIPELINE DE FILTRADO (LLM)                         │
│      │    ├── ¿Relevante para SDP/aviación?                     │
│      │    ├── ¿Podemos aportar valor?                            │
│      │    ├── ¿Es seguro responder?                              │
│      │    └── ¿Cumple límites de usuario/tiempo?                 │
│      │                                                           │
│      ├──▶ 5. PIPELINE DE RESPUESTA                              │
│      │    ├── Elegir estilo (1-5)                                │
│      │    ├── Redactar en tono adecuado                          │
│      │    └── Publicar (reply_tweet.py)                          │
│      │                                                           │
│      └──▶ 6. Actualizar contadores + log                         │
│                                                                  │
│   ┌────────────────────────────────┐                            │
│   │         GETXAPI (API)          │                            │
│   │  api.getxapi.com               │                            │
│   │  - /tweet/advanced_search      │                            │
│   │  - /tweet/create               │                            │
│   │  - /user/info                  │                            │
│   └────────────────────────────────┘                            │
└────────────────────────────────────────────────────────────────┘
```

---

## 2. Componentes

### 2.1. Scripts Python

| Script | Función | Dependencias |
|--------|---------|--------------|
| `scripts/search_tweets.py` | Búsqueda de tweets vía GetXAPI | requests, json |
| `scripts/reply_tweet.py` | Publicar respuestas vía GetXAPI | requests, json |

### 2.2. Documentación

| Archivo | Propósito |
|---------|-----------|
| `docs/ARCHITECTURE.md` | Este documento |
| `docs/API.md` | Endpoints de GetXAPI |
| `docs/CONFIGURATION.md` | Keywords, límites, temas |
| `docs/OPERATION.md` | Operación diaria |
| `docs/FUTURE.md` | Funcionalidades planificadas |
| `docs/INSTALL.md` | Guía de instalación |

### 2.3. Datos

| Archivo | Tipo | Propósito |
|---------|------|-----------|
| `config/limites.json` | JSON | Límites diarios configurables |
| `data/tweets_all.json` | JSON | 99 tweets extraídos para análisis |
| `data/categorizacion.json` | JSON | Tweets categorizados por estilo |
| `data/analisis_estilo.md` | Markdown | Análisis de estilo de escritura |
| `data/INSIGHTS_algoritmo_X.md` | Markdown | Algoritmo "For You" de X |
| `logs/actividad.log` | JSONL | Registro de actividad del bot |

---

## 3. Flujo de datos detallado

### 3.1. Pipeline de búsqueda

```
[Inicio]
    │
    ▼
┌──────────────────┐
│  search_tweets.py │
│  ─────────────── │
│                   │
│  1. Leer .env     │
│  2. Construir     │
│     query según   │
│     modo           │
│  3. GET → GetXAPI │
│  4. Parsear JSON  │
│  5. Limitar a     │
│     20 resultados │
│  6. Devolver      │
│     resultados    │
└──────┬───────────┘
       │
       ▼ Los tweets pasan al pipeline de filtrado (lo ejecuta el LLM/Hermes)
```

### 3.2. Pipeline de respuesta

```
[Tweet candidato]
    │
    ▼
┌──────────────────────┐
│  FILTRO 1:           │
│  ¿Relevante?         │
│  - Sector            │
│  - Tema laboral      │
│  - Barajas/aviación  │
└──────┬─ Sí ─────────┘
       │ No → DESCARTA
       ▼
┌──────────────────────┐
│  FILTRO 2:           │
│  ¿Aporta valor?      │
│  - Información       │
│  - Apoyo             │
│  - Debate            │
└──────┬─ Sí ─────────┘
       │ No → DESCARTA
       ▼
┌──────────────────────┐
│  FILTRO 3:           │
│  ¿Seguro?            │
│  - Tono respetuoso   │
│  - No troll/spam     │
│  - No provocación    │
└──────┬─ Sí ─────────┘
       │ No → DESCARTA
       ▼
┌──────────────────────┐
│  FILTRO 4:           │
│  ¿Límites OK?        │
│  - < 7 días        │
│  - 1/3/10 regla    │
│  - No duplicado    │
└──────┬─ Sí ─────────┘
       │ No → DESCARTA
       ▼
┌──────────────────────┐
│  Elegir estilo +     │
│  redactar respuesta  │
│  (LLM determina)     │
└──────┬───────────────┘
       ▼
┌──────────────────────┐
│  reply_tweet.py      │
│  ────────────────── │
│                       │
│  1. Leer .env         │
│  2. POST → GetXAPI    │
│     /tweet/create     │
│  3. Log resultado     │
│  4. Actualizar        │
│     contadores        │
└──────────────────────┘
```

---

## 4. Decisiones arquitectónicas

### 4.1. ¿Por qué GetXAPI y no X API oficial?

| Factor | X API oficial | GetXAPI |
|--------|:------------:|:-------:|
| Coste de búsqueda | $0.001 | $0.001 |
| Coste de respuesta | $0.200 | $0.002 |
| Coste mensual estimado | ~$61.65 | ~$2.55 |
| Auth requerido | OAuth 2.0 complejo | API key + token |
| Límites Free | 500 búsquedas/mes | Pay-per-use |

GetXAPI es **100x más barato** para respuestas y más sencillo de configurar.

### 4.2. ¿Por qué Python en lugar de Node/Go?

- El usuario ya tiene Python instalado
- `requests` + `json` son suficientes para esta carga
- Fácil de leer y modificar

### 4.3. ¿Por qué no un framework web?

- El bot es reactivo (busca y responde), no tiene interfaz web
- Para v2.0 se plantea una interfaz de gestión (ver FUTURE.md)

---

## 5. Seguridad

- 🔐 Las claves API **nunca** se almacenan en el repositorio
- 🔐 `.env` está en `.gitignore` — siempre exclusión local
- 🔐 El `auth_token` de X se almacena solo en `.env`
- 🔐 Los logs no contienen credenciales
