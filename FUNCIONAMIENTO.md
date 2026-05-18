# 🧠 Funcionamiento del Bot @sindicatosdpMAD

> Documento técnico de funcionamiento, búsqueda, filtrado y estrategia algorítmica
> Basado en análisis de 99 tweets reales + algoritmo "For You" de X (publicado por xAI, mayo 2026)

---

## Índice

1. [Arquitectura General](#1-arquitectura-general)
2. [Pipeline de Búsqueda](#2-pipeline-de-búsqueda)
3. [Pipeline de Filtrado](#3-pipeline-de-filtrado)
4. [Pipeline de Respuesta](#4-pipeline-de-respuesta)
5. [Cómo crear Tuits Algorítmicamente Interesantes](#5-cómo-crear-tuits-algorítmicamente-interesantes)
6. [Las 22 Señales del Algoritmo de X](#6-las-22-señales-del-algoritmo-de-x)
7. [Optimización para el Algoritmo](#7-optimización-para-el-algoritmo)
8. [Límites y Control de Costes](#8-límites-y-control-de-costes)
9. [Diagrama de Flujo Completo](#9-diagrama-de-flujo-completo)

---

## 1. Arquitectura General

```
┌─────────────────────────────────────────────────────────────────┐
│                        HERMES AGENT                              │
│                                                                   │
│  ⏰ Cronjob (cada 60 min)                                         │
│     │                                                             │
│     ├─▶ Carga Skill x-bot-sindicatosdp (estilo + reglas)         │
│     │                                                             │
│     ├─▶ Lee contadores (~/.hermes/xbot-counters.json)            │
│     │                                                             │
│     ├─▶ FASE 1: BÚSQUEDA                                         │
│     │   ├─ search.py → X API v2 (Bearer Token)                   │
│     │   ├─ search.py --mentions → menciones a @sindicatosdpMAD   │
│     │   └─ search.py --from → tweets de cuentas clave            │
│     │                                                             │
│     ├─▶ FASE 2: FILTRADO (LLM)                                   │
│     │   ├─ ¿Es relevante para SDP?                               │
│     │   ├─ ¿Podemos aportar valor?                               │
│     │   ├─ ¿Es seguro responder?                                 │
│     │   └─ ¿Cumple límites de usuario/ventana?                   │
│     │                                                             │
│     ├─▶ FASE 3: RESPUESTA                                        │
│     │   ├─ Elegir estilo (1-5)                                   │
│     │   ├─ Redactar en el tono adecuado                          │
│     │   └─ reply.py → xurl reply o API directa                   │
│     │                                                             │
│     └─▶ Actualiza contadores + log                                │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│                        X / TWITTER                                │
│  API v2 (Bearer Token) ← búsquedas                               │
│  xurl (OAuth 1.0a/2.0) → respuestas                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Pipeline de Búsqueda

### 2.1. Fuentes de datos

El bot consulta **3 fuentes** en cada ejecución:

| Fuente | Método | Propósito |
|--------|--------|-----------|
| **Búsqueda por keywords** | `GET /2/tweets/search/recent` | Encontrar conversaciones activas sobre temas del sindicato |
| **Menciones** | `GET /2/users/{id}/mentions` | No ignorar a quien nos habla directamente |
| **Cuentas clave** | `GET /2/tweets/search/recent?from:cuenta` | Monitorizar sindicatos afines y fuentes del sector |

### 2.2. Query de búsqueda principal

```python
query = (
    "(huelga OR \"servicios mínimos\" OR trabajadores OR "
    "\"derecho de huelga\" OR sindicato OR SAERCO OR aena OR "
    "controladores OR handling OR plataforma) "
    "lang:es -is:retweet"
)
```

**Filtros aplicados:**
- `lang:es` — Solo español
- `-is:retweet` — Sin retweets, solo contenido original
- `max_results: 20` — Top 20 tweets más recientes

### 2.3. Cuentas monitorizadas (del análisis real)

@USCAnet, @controladores, @SAERCO_ANS, @aena, @hosteltur, @transportesgob, @instrabajoyss, @JulenBollain, @javierglezv, @FSCdeCCOO, @aereoccoo

Se buscan sus tweets que contengan: `(huelga OR sindicato OR trabajadores OR laboral OR derechos)`

### 2.4. Autenticación

Usamos **OAuth 2.0 Client Credentials** (app-only) para lectura:

```python
# Generar bearer token desde consumer key/secret
creds = base64(f"{CONSUMER_KEY}:{CONSUMER_SECRET}")
POST /oauth2/token → {"access_token": "AAAA..."}
```

Para escritura (respuestas) se necesita **xurl con OAuth 1.0a o 2.0** (pendiente configurar app en X Developers).

---

## 3. Pipeline de Filtrado

Cada tweet candidato pasa por **4 filtros secuenciales**. Si falla cualquiera, se descarta.

### 3.1. Filtro de Relevancia Temática

Preguntas que responde el LLM:

1. **¿Habla del sector laboral-aeroportuario?**
   - Huelgas, servicios mínimos, condiciones laborales
   - Aviación, aeropuertos, handling, controladores
   - Sindicatos, convenios, derechos de trabajadores

2. **¿Está dentro de nuestras temáticas?**
   - Derecho de huelga (tema #1 del análisis)
   - Condiciones laborales de trabajadores
   - Empresas que vulneran derechos
   - Jurisprudencia laboral
   - Comparativa Europa vs España

### 3.2. Filtro de Valor Aportado

3. **¿Podemos aportar algo?**
   - ¿Podemos dar información útil o matizar?
   - ¿Podemos mostrar apoyo o solidaridad?
   - ¿Podemos compartir jurisprudencia relevante?
   - ¿Podemos agradecer un gesto positivo?

### 3.3. Filtro de Seguridad

4. **¿Es seguro responder?**
   - ¿El tono del original es respetuoso?
   - ¿No es provocación/trampa?
   - ¿La cuenta no es spam/bot?

### 3.4. Filtro de Límites Operativos

5. **¿Cumple límites?**
   - ¿Ya respondimos a este usuario hoy? (check en historial_usuarios)
   - ¿El tweet tiene menos de 7 días?
   - ¿No hemos llegado al máximo de respuestas en esta ejecución?

---

## 4. Pipeline de Respuesta

### 4.1. Los 5 Estilos de Respuesta

Identificados del análisis real de 99 tweets:

| # | Estilo | % | Cuándo | Formato |
|---|--------|---|--------|---------|
| 1 | **⚪ Apoyo** | 36% | Compañero que expresa queja/preocupación | `@usuario [1-10 palabras]` |
| 2 | **🟣 Reivindicativo** | 26% | Debate sobre derechos laborales | `@usuario [argumento + ¿pregunta retórica?]` |
| 3 | **💬 Cita con opinión** | 14% | Compartir noticia con comentario propio | `[opinión directa, sin @]` |
| 4 | **📜 Jurídico** | 8% | Compartir sentencias/argumentos legales | `[cita legal] ➡️ [explicación]` |
| 5 | **✊ Denuncia directa** | 3% | Señalar situación injusta | `[sujeto]: [acción]. [reacción].` |

### 4.2. Reglas de Estilo (NO negociables)

- **NO usar hashtags** — el uso real es 0 en 99 tweets
- **NO usar emojis** — a menos que el tweet original los tenga
- **No entrar en política partidista**
- **No compartir información no verificada**
- **No responder a bots o spam**

### 4.3. Mecanismo de respuesta

```bash
# Paso 1: Verificar que xurl está auth
xurl auth status

# Paso 2: Responder
xurl reply <tweet_id> "mensaje"

# O vía script
python3 reply_tweet.py <tweet_id> "mensaje" @usuario
```

---

## 5. Cómo crear Tuits Algorítmicamente Interesantes

> Basado en el análisis del código fuente del algoritmo "For You" de X, publicado por xAI el 15/05/2026.

### 5.1. Principio fundamental

El algoritmo no optimiza "engagement" abstracto. **Predice 22 acciones del lector** y las combina con pesos. Tu objetivo es maximizar las señales positivas y **minimizar las negativas** (que RESTAN, no solo no-suman).

### 5.2. Las 4 palancas principales para @sindicatosdpMAD

Basado en nuestro perfil (76.8% replies, contenido jurídico-laboral):

#### 🔵 Palanca 1: Generar `dwell` (tiempo de lectura)

El algoritmo mide si el lector se queda o hace scroll (`not_dwelled`). Esta señal negativa es la más dañina.

**Cómo lo logramos:**
- Textos con estructura: titulares cortos + desarrollo
- Datos y cifras que invitan a leer con atención
- Preguntas retóricas que activan el pensamiento del lector
- Citas legales exactas (STC, STS, SAN) que aportan autoridad

**Ejemplo de estructura que maximiza dwell:**
```
📌 STC 2/2022, de 24 de enero

➡️ la empresa no puede aprovechar la capacidad "sobrante" 
del personal mínimo para realizar trabajo ordinario no esencial.

El TC recuerda que los servicios mínimos...

¿Y en España qué pasa? Exacto: lo ignoran.
```

#### 🟢 Palanca 2: Generar `reply` (respuestas)

Históricamente, `reply` es una de las señales con más peso.

**Cómo lo logramos:**
- Preguntas retóricas al final del tweet
- Opiniones claras que invitan a posicionarse
- Denuncias concretas que otros quieren comentar/apoyar
- Datos que invitan a ser matizados

**Ejemplo:**
```
Y durante una huelga, considerando los servicios mínimos 
declarados por el ministerio, COMO ES POSIBLE que aumenten 
un 70% el tráfico mientras se cumple la ley?

Respuesta: no cumplen la ley.
```

#### 🟡 Palanca 3: Generar `retweet` (compartibilidad)

Contenido que la gente quiere compartir porque:
- Representa una postura que otros quieren adoptar
- Contiene verdades incómodas que merecen difusión
- Datos útiles para el sector

**Ejemplo:**
```
En Europa las huelgas se siguen sucediendo con normalidad.
En España tienen secuestrados a los trabajadores.

Hay que poner fin a estas vulneraciones sistemáticas.
```

#### 🔴 Palanca 4: Evitar `not_dwelled` (el asesino silencioso)

**Lo que mata el dwell en nuestro contexto:**
- ❌ Titulares vagos sin contenido detrás
- ❌ Hilos infinitos (DedupConversationFilter solo muestra 1 tweet)
- ❌ Respuestas demasiado genéricas ("Estoy de acuerdo 👍")
- ❌ Spamear desde la misma cuenta (Author Diversity Decay)

### 5.3. El "Banger Initial Screen"

Grok-VLM puntúa cada **post original** con un `quality_score` (0-1). El umbral para ser "banger" es **≥ 0.4**.

**Lo que Grok valora:**
- Contenido sustancial, no genérico
- Información verificable (citas legales exactas)
- Opiniones fundamentadas
- Originalidad (el `slop_score` penaliza AI slop)

**Lo que NO pasan este filtro:**
- Replies (no se evalúan como bangers)
- Retweets
- Cuentas privadas

### 5.4. Ventana de oportunidad temporal

| Tiempo | Estado |
|--------|--------|
| 0-30 min | ⚠️ Crítico. El engagement temprano determina si entra al pipeline de Grok |
| 30-60 min | ✅ Ventana de descubrimiento amplio |
| 1-24 h | ✅ Alcance máximo |
| 24-80 h | ⬇️ Declive progresivo |
| >80 h | ❌ "Overflow bucket" — el algoritmo lo trata como muy viejo |

### 5.5. Author Diversity Decay

Cada post adicional del mismo autor en el feed se multiplica por un factor decreciente:
- 1er post: × 1.0
- 2do post: × 0.5 (ejemplo)
- 3er post: × 0.25
- 4to+: × 0.1

**Implicación:** No tiene sentido publicar/bombardear. Espacia el contenido.

---

## 6. Las 22 Señales del Algoritmo de X

### 6.1. Señales Positivas (suman al score)

| Señal | Qué predice | Cómo activarla |
|-------|-------------|----------------|
| `favorite` | Probabilidad de like | Hooks emocionales, opiniones claras |
| `reply` | Probabilidad de respuesta | Preguntas, opiniones polarizantes |
| `retweet` | Probabilidad de RT | Datos sorprendentes, frases citables |
| `photo_expand` | Expandir imagen | Imágenes con detalle |
| `click` | Click en enlaces | Enlaces con curiosity gap |
| `profile_click` | Click en perfil | Bio interesante |
| `vqv` | Video Quality View | Vídeo nativo de calidad |
| `dwell` | Tiempo de阅读 | Texto denso pero legible |
| `follow_author` | Seguir al autor | Punto de vista único |

### 6.2. Señales Negativas (RESTAN — más peso que las positivas)

| Señal | Qué predice | Qué la dispara |
|-------|-------------|----------------|
| `not_interested` | "No me interesa" | Contenido off-topic |
| `block_author` | Bloqueo | Insultos, ataques |
| `mute_author` | Mute | Posteo excesivo |
| `report` | Denuncia | Contenido que cruza líneas |
| `not_dwelled` | Scroll sin parar | **El post aburre** |

> ⚠️ **Las señales negativas tienen pesos órdenes de magnitud mayores que las positivas.** Un solo "report" puede borrar el efecto de varios likes.

---

## 7. Optimización para el Algoritmo

### 7.1. Checklist de calidad para cada respuesta

Antes de responder, verificar:

- [ ] **¿Aporta información nueva?** (no repetir lo dicho)
- [ ] **¿Tiene un hook claro?** (primeras 2 líneas que enganchan)
- [ ] **¿Invita a la interacción?** (pregunta, dato, opinión)
- [ ] **¿Evita ser genérico?** ("apoyo" sí, pero con sustancia)
- [ ] **¿Cita fuente si es legal?** (STC, STS, SAN + número)
- [ ] **¿Estructura visual clara?** (saltos de línea, sin muros de texto)
- [ ] **¿Sin hashtags?** (0 en el análisis real)
- [ ] **¿Sin emojis?** (solo si el original los tiene)

### 7.2. Estructura óptima de un tweet

```
[HOOK — 1-2 líneas que captan atención]
[Dato, cita o argumento — 2-4 líneas]
[Pregunta retórica o cierre contundente — 1 línea]
```

**Ejemplo real de la cuenta:**
```
Huelgas
Italia 11/05 (1 dia): controladores ENAV generaron ~210 cancelaciones

España 17/04 (60 dias): 0 cancelaciones por vulneración de derecho 
a huelga de @SAERCO_ANS

Así se les niega el derecho constitucional y europeo a la huelga efectiva
```

### 7.3. Estrategia de "min-traction" (primeros 30 min)

Para que un post original entre en el pipeline de Grok:
1. Publicar en hora de alta actividad del sector (mañana laboral)
2. Mencionar cuentas afines que pueden interactuar (@USCAnet, @controladores, etc.)
3. El contenido debe ser lo suficientemente polarizante/importante para generar engagement rápido
4. Evitar publicar cuando hay eventos masivos compitiendo por atención

### 7.4. Regla del hilo único

DedupConversationFilter mantiene **solo 1 tweet por conversación** en el feed. No hagas hilos de 8 tweets esperando dominar el feed — elige tu mejor tweet y haz que ese destaque.

---

## 8. Límites y Control de Costes

### 8.1. Límites diarios

| Parámetro | Valor | Cálculo de coste |
|-----------|-------|-------------------|
| Max búsquedas/día | 20 | 20 × 1 llamada API = 20 de 500/mes Free |
| Max respuestas/día | 10 | 10 × 1 post = 10 de 1500/mes Free |
| Max respuestas/ejecución | 3 | Para no saturar |
| Max respuestas/mismo usuario/día | 1 | Evitar spam percibido |
| Ventana de tweets | ≤7 días | El algoritmo capa a 80h (~3.3 días) |

### 8.2. Fichero de contadores

Ruta: `~/.hermes/xbot-counters.json`

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

Los contadores se reinician automáticamente al cambiar la fecha.

### 8.3. Costes de API de X

| Recurso | Límite Free | Uso diario estimado | Consumo mensual |
|---------|-------------|---------------------|-----------------|
| Posts (tweets + replies) | 1,500/mes | 10 respuestas | ~300/mes (✅) |
| Búsquedas (search recent) | 500/mes | 20 búsquedas | ~600/mes (⚠️ excede) |
| Lectura de timeline | 100,000/mes | ~20/día | ~600/mes (✅) |

> ⚠️ Las búsquedas están al límite. Si el bot busca más de 16 veces al día, se necesitará el plan Basic ($100/mes).

---

## 9. Diagrama de Flujo Completo

```
INICIO (cada 60 min)
│
├─ 1. Cargar skill x-bot-sindicatosdp
│
├─ 2. Leer ~/.hermes/xbot-counters.json
│   ├─ fecha == hoy?
│   │   ├─ Sí → usar contadores existentes
│   │   └─ No → reiniciar contadores a 0
│   │
│   └─ ¿Límites agotados?
│       ├─ Sí → FIN (reportar en log)
│       └─ No → CONTINUAR
│
├─ 3. BUSCAR (3 fuentes en paralelo)
│   ├─ Búsqueda por keywords (20 tweets)
│   ├─ Menciones (20 tweets)
│   └─ Cuentas clave (5 tweets × 3 cuentas)
│
├─ 4. FILTRAR (por cada tweet candidato)
│   ├─ ¿Relevante? → No → DESCARTAR
│   ├─ ¿Aporta valor? → No → DESCARTAR
│   ├─ ¿Seguro? → No → DESCARTAR
│   ├─ ¿Límites? → No → DESCARTAR
│   └─ Sí → CANDIDATO VÁLIDO
│
├─ 5. Si NO hay candidatos → FIN
│
├─ 6. Para cada candidato (máx 3):
│   ├─ Elegir estilo (1-5)
│   ├─ Redactar respuesta según estilo
│   ├─ Verificar reglas de calidad (§7)
│   ├─ Publicar: xurl reply <id> "msg"
│   └─ Actualizar contadores
│
├─ 7. Guardar contadores
│
├─ 8. Generar resumen para el usuario
│
└─ FIN
```

---

## 📁 Estructura de ficheros

```
~/.hermes/
├── skills/
│   └── x-bot-sindicatosdp/
│       └── SKILL.md                  ← Personalidad + reglas
├── xbot-counters.json                ← Contadores diarios

~/proyectos/agente-x-sindicatosdp/
├── ALCANCE_Y_DISENO.md               ← Documento de alcance
├── FUNCIONAMIENTO.md                  ← Este documento
├── data/
│   ├── tweets_all.json               ← 99 tweets extraídos
│   ├── categorizacion.json           ← Categorizados por estilo
│   ├── analisis_estilo.md            ← Análisis de estilo
│   └── INSIGHTS_algoritmo_X.md       ← Algoritmo For You de X
├── scripts/
│   ├── search_tweets.py              ← Buscador (X API v2)
│   └── reply_tweet.py                ← Respondedor (xurl)
└── logs/
    └── actividad.log                 ← Registro de actividad
```
