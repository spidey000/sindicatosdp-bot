# 🤖 Agente Autónomo X — @sindicatosdpMAD

> **Documento de Alcance, Diseño y Configuración**
> Proyecto: Subagente autónomo para buscar y responder en X/Twitter
> Cuenta: [@sindicatosdpMAD](https://x.com/sindicatosdpMAD)
> Propietario: Jorge Martín — Delegado de Personal SDP, Aeropuerto Madrid-Barajas
> Fecha: 18/05/2026

---

## Índice

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Arquitectura del Sistema](#2-arquitectura-del-sistema)
3. [Requisitos Técnicos](#3-requisitos-técnicos)
4. [Autenticación en X (Twitter)](#4-autenticación-en-x-twitter)
5. [Personalidad y Estilo (@sindicatosdpMAD)](#5-personalidad-y-estilo-sindicatosdpmad)
6. [Criterios de Búsqueda](#6-criterios-de-búsqueda)
7. [Estrategia de Respuesta](#7-estrategia-de-respuesta)
8. [Límites y Control de Costes](#8-límites-y-control-de-costes)
9. [Sistema de Almacenamiento](#9-sistema-de-almacenamiento)
10. [Configuración del Cronjob](#10-configuración-del-cronjob)
11. [Plan de Implementación](#11-plan-de-implementación)
12. [Mantenimiento y Monitorización](#12-mantenimiento-y-monitorización)
13. [Anexos](#13-anexos)

---

## 1. Resumen Ejecutivo

### 1.1. ¿Qué vamos a construir?

Un **agente autónomo** que funciona dentro de **Hermes Agent** (el sistema de IA que ya tienes instalado) y que:

1. **Busca tweets** en X/Twitter sobre temas relevantes para el sindicato SDP de Madrid-Barajas
2. **Analiza** qué tweets merecen una respuesta (no responde a todo)
3. **Responde** con mensajes escritos en tu estilo personal y sindical
4. **Respeta límites** diarios configurables para no disparar el consumo de API de X

### 1.2. ¿Por qué dentro de Hermes y no en un repo externo?

| Opción | Ventajas | Desventajas |
|--------|----------|-------------|
| Repo externo (GitHub) | Ya existe alguien que lo hizo | No conoce tu estilo, tu sector, ni tu cuenta. Difícil de adaptar. Dependencia externa. |
| **Hermes + xurl + cronjob** | Usa tu modelo (DeepSeek), conoce tu contexto, todo corre local, control total. Fácil de iterar. | Hay que configurarlo una vez. |

Hermes ya tiene todo lo necesario:
- Un **LLM potente** (DeepSeek) para entender tweets y redactar respuestas naturales
- **Cronjobs** para ejecución periódica con límites
- **Skills** para almacenar conocimiento reutilizable
- **Memoria persistente** entre sesiones

### 1.3. Flujo de alto nivel

```
Cronjob (cada N minutos)
    │
    ▼
1. Verificar límites diarios (fichero de contadores)
    │
    ▼ (si no se han agotado)
2. Buscar tweets relevantes en X (vía xurl search)
    │
    ▼
3. Analizar cada tweet: ¿es relevante? ¿merece respuesta?
    │
    ▼ (si hay candidatos)
4. Generar respuesta en el estilo de @sindicatosdpMAD
    │
    ▼
5. Publicar respuesta (vía xurl reply)
    │
    ▼
6. Actualizar contadores diarios
    │
    ▼
7. Esperar hasta la siguiente ejecución
```

---

## 2. Arquitectura del Sistema

### 2.1. Diagrama de componentes

```
┌─────────────────────────────────────────────────────────────┐
│                   H E R M E S   A G E N T                    │
│                                                              │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────┐   │
│  │   Cronjob    │───▶│   Agente     │───▶│  Terminal Tool  │   │
│  │  (scheduler) │    │  (DeepSeek)  │    │  (ejecuta cmds) │   │
│  └─────────────┘    └──────┬───────┘    └───────┬────────┘   │
│                            │                    │              │
│                            ▼                    ▼              │
│                     ┌──────────────┐    ┌──────────────┐      │
│                     │   Memory    │    │    xurl CLI   │      │
│                     │  + Skills   │    │  (X API v2)   │      │
│                     └──────────────┘    └──────┬───────┘      │
│                                                  │              │
└──────────────────────────────────────────────────┼──────────────┘
                                                   │
                                                   ▼
                                        ┌──────────────────┐
                                        │  X API (Twitter) │
                                        │  - search tweets  │
                                        │  - post replies   │
                                        └──────────────────┘
```

### 2.2. Componentes detallados

| Componente | Rol | Tecnología |
|-----------|-----|------------|
| **Hermes Agent** | Orquestador principal. Ejecuta el agente, proporciona herramientas. | Hermes (ya instalado) |
| **Cronjob** | Dispara la ejecución periódica (ej. cada 60 min) | Sistema interno de Hermes |
| **Agente (LLM)** | Analiza tweets, decide si responder, redacta respuestas | DeepSeek (modelo activo) |
| **xurl CLI** | Interactúa con X API v2 (buscar, responder, leer) | CLI oficial de X |
| **Skill** | Almacena estilo, criterios, configuración reutilizable | Fichero SKILL.md en Hermes |
| **Contadores** | Archivos JSON con límites diarios (búsquedas, respuestas) | Ficheros en ~/.hermes/ |
| **Memoria** | Patrones aprendidos, ajustes de estilo, preferencias | Sistema de memoria de Hermes |

### 2.3. Flujo detallado de una ejecución

```
INICIO
│
├─▶ 1. El cronjob se activa (según schedule configurado)
│
├─▶ 2. Se carga el skill "x-bot-sindicatosdp" (contiene estilo + criterios)
│
├─▶ 3. Se lee el fichero de contadores: ~/.hermes/xbot-counters.json
│     ├─ Si límite_diario_búsquedas > contador_búsquedas → CONTINUAR
│     ├─ Si límite_diario_respuestas > contador_respuestas → CONTINUAR
│     └─ Si algún límite agotado → FIN (informa en log)
│
├─▶ 4. Búsqueda en X:
│     ├─ keywords definidos en el skill
│     ├─ filtros: idioma español, fecha reciente, etc.
│     └─ resultado: lista de tweets con ID, texto, autor, fecha
│
├─▶ 5. Filtrado y análisis (lo hace el LLM):
│     ├─ ¿El tweet es relevante para el sindicato SDP?
│     ├─ ¿El tono es constructivo / merece engagement?
│     ├─ ¿Podemos aportar valor respondiendo?
│     └─ Se seleccionan máximo N candidatos
│
├─▶ 6. Para cada candidato:
│     ├─ Leer contexto del tweet (hilo, respuestas existentes)
│     ├─ Generar respuesta acorde al estilo guardado en el skill
│     ├─ Publicar vía: xurl reply <tweet_id> "mensaje"
│     └─ Incrementar contador_respuestas
│
├─▶ 7. Guardar contadores actualizados
│
└─▶ FIN
```

---

## 3. Requisitos Técnicos

### 3.1. Software necesario

| Software | Estado | Notas |
|----------|--------|-------|
| Hermes Agent | ✅ Instalado | Versión actual con cronjobs y skills |
| xurl CLI | ✅ Instalado | CLI oficial de X (Twitter) v2.0.13. Pendiente OAuth |
| DeepSeek (modelo) | ✅ Activo | Modelo actual de Hermes |
| Node.js / npm | ✅ Instalado | Para instalar xurl |
| Python 3 | ✅ Instalado | Con requests, json |
| Camofox (browser) | ✅ Instalado | Navegador anti-detección para login en X |

### 3.2. Cuentas necesarias

| Cuenta | Estado | Notas |
|--------|--------|-------|
| @sindicatosdpMAD en X | ✅ Activa | La cuenta del sindicato |
| App en X Developers | ❌ Pendiente crear | Necesaria para OAuth de xurl. De momento usamos API v2 con Bearer Token |
| Plan X API | ✅ Free | Bearer token funcional. 500 búsquedas/mes, 1500 posts/mes |

### 3.3. Instalación de xurl

```bash
# Método recomendado para Linux:
curl -fsSL https://raw.githubusercontent.com/xdevplatform/xurl/main/install.sh | bash

# Verificar instalación:
xurl --help
```

*(La configuración de autenticación se detalla en la [sección 4](#4-autenticación-en-x-twitter))*

---

## 4. Autenticación en X (Twitter)

### 4.1. Crear App en X Developers

Pasos que debe hacer Jorge en el portal de X:

1. Ir a https://developer.x.com/en/portal/dashboard
2. Crear una nueva aplicación (o usar una existente)
3. Configurar el tipo como **"Web App, Automated App or Bot"**
4. Establecer el **Redirect URI** a: `http://localhost:8080/callback`
5. Copiar el **Client ID** y **Client Secret**

### 4.2. Configurar xurl con OAuth 2.0

```bash
# Registrar la app en xurl:
xurl auth apps add sindicatosdp --client-id TU_CLIENT_ID --client-secret TU_CLIENT_SECRET

# Iniciar flujo OAuth (se abrirá navegador):
xurl auth oauth2 --app sindicatosdp

# Establecer como app por defecto:
xurl auth default sindicatosdp

# Verificar:
xurl auth status
xurl whoami
```

> ⚠️ **IMPORTANTE:** El flujo OAuth abre un navegador para autorizar la app. Si estás en un servidor sin interfaz gráfica, se puede hacer con `--headless` o desde tu máquina local y copiar el fichero `~/.xurl` al servidor.

### 4.3. Verificación final

```bash
# Probar búsqueda:
xurl search "aeropuerto Madrid" -n 3

# Probar lectura de perfil propio:
xurl whoami
```

---

## 5. Personalidad y Estilo (@sindicatosdpMAD)

### 5.1. ¿Dónde se almacena?

Todo el estilo se guarda en un **Skill de Hermes** llamado `x-bot-sindicatosdp`. Este skill se carga cada vez que el cronjob se ejecuta, y contiene:

- La personalidad de la cuenta
- El tono y estilo de escritura
- Temas sobre los que hablar
- Ejemplos de respuestas tipo
- Instrucciones de comportamiento

### 5.2. Definición de la personalidad

> Basado en el análisis real de 99 tweets extraídos el 18/05/2026 vía X API v2

**Perfil de la cuenta:**
- Cuenta oficial del **Sindicato de Dirección de Plataforma (SDP)** del Aeropuerto Adolfo Suárez Madrid-Barajas
- Representa a los trabajadores del servicio de plataforma (rampa, handling, coordinación)
- Gestión a cargo de Jorge Martín, delegado de personal
- **Perfil predominantemente reactivo:** 76.8% de los tweets son respuestas a otros usuarios
- **Sin hashtags** — no se utiliza ningún hashtag en ningún tweet
- **Emojis mínimos** — uso casi nulo (➡ 😮 🧵 🤷 ♂️ aparecen raramente)

**Tono y voz:**

| Atributo | Descripción |
|----------|-------------|
| Tono general | Profesional, jurídico, firme. Lenguaje preciso |
| Formalidad | Semi-formal con tendencia a técnico-jurídico |
| Emotividad | Racional y argumentativo. Apoyo cálido pero escueto |
| Longitud | Variable: desde 1 palabra ("ánimo!") hasta tuits de 3-4 párrafos |
| Hashtags | **Ninguno** — patrón confirmado en 99 tweets |
| Emojis | Casi nulos. No usar por defecto |
| Estilo predominante | Debate/denuncia sobre derechos laborales y huelgas |

**Temáticas principales (ordenadas por frecuencia real):**
1. **Derecho de huelga** — tema central, palabra más usada (34 veces)
2. **Condiciones laborales de trabajadores** (24 menciones)
3. **Empresas que vulneran derechos** (21 menciones: "empresa")
4. **Servicios mínimos** y su cumplimiento/incumplimiento (20 menciones)
5. **Jurisprudencia y sentencias** — citas legales frecuentes (STC, STS, SAN)
6. **Comparativa Europa vs España** — patrón recurrente de denuncia
7. **Aviación civil** — controladores, handling, aerolíneas

**Lo que NO se hace:**
- ❌ No se responde a insultos o provocaciones
- ❌ No se entra en debates políticos partidistas
- ❌ No se comparte información no verificada
- ❌ No se usan mayúsculas sostenidas (gritar)
- ❌ No se responde a bots o cuentas spam

### 5.3. Ejemplos de respuestas tipo (reales, extraídos del análisis)

**Estilo 1 — Respuesta de apoyo (36% de los tweets):**
> "@usuario ánimo!"

> "@usuario Gracias por el apoyo, compañero"

*Características: Ultra-breve, 1-5 palabras. Sin adornos. Directo al grano.*

**Estilo 2 — Respuesta reivindicativa (26% de los tweets):**
> "@usuario literalmente, solo el sindicalismo de clase soluciona los problemas de los trabajadores"

> "@usuario Y durante una huelga, considerando los servicios mínimos declarados por el ministerio, COMO ES POSIBLE que aumenten un 70% el tráfico mientras se cumple la ley? Respuesta: no cumplen la ley."

*Características: Argumentativo. Preguntas retóricas. MAYÚSCULAS para énfasis. Comparativas.*

**Estilo 3 — Cita con opinión (14% de los tweets):**
> "Y en europa las huelgas se siguen sucediendo con normalidad mientras en España tienen secuestrados a los trabajadores"

*Características: Sin @. Opinión directa. Comparativa Europa/España. Tono de denuncia.*

**Estilo 4 — Tuit jurídico (8% de los tweets):**
> "STC 2/2022, de 24 de enero. ➡️ la empresa no puede aprovechar la capacidad 'sobrante' del personal mínimo para realizar trabajo ordinario no esencial. El TC recuerda que los servicios..."

*Características: Cita legal exacta (STC, STS, SAN). Lenguaje técnico. Hechos, no opinión.*

**Estilo 5 — Tuit reivindicativo directo (3% de los tweets):**
> "Sindicato @USCAnet: queremos atender los ssmm de 50%. @SAERCO_ANS: NO! teneis que atender el 100%"

> "Pregunta para @instrabajoyss: En huelga de servicio esencial... 1) NO ssmm que pueden ir o no. 2) Si ssmm: tendrán que ir y atender UNICAMENTE a los s.esenciales"

*Características: Formato diálogo. Preguntas directas. Listados numéricos. Denuncia.*

### 5.4. Criterios de afinidad temática

El agente priorizará respuestas a tweets sobre:

1. **Trabajadores y condiciones laborales** (sueldos, horarios, turnos, descansos)
2. **Seguridad en plataforma** (incidentes, protocolos, equipamiento)
3. **Aena y gestión aeroportuaria** (decisiones, cambios organizativos)
4. **Handling y operativa** (empresas de handling, coordinación)
5. **Sindicatos y derechos laborales** (negociación colectiva, convenios)
6. **Aeropuerto Madrid-Barajas** (noticias, obras, expansión)
7. **Aviation laboral en España** (contexto nacional del sector)

---

## 6. Criterios de Búsqueda

### 6.1. Keywords y queries para X Search

El agente usará el operador `xurl search` con combinaciones de las siguientes palabras clave:

**Grupo 1 — Términos principales (prioridad alta):**
```
"sindicato" "SDP" "dirección de plataforma" "trabajadores aeropuerto" "Barajas" "Madrid-Barajas"
```

**Grupo 2 — Términos sectoriales (prioridad media):**
```
"handling" "Aena" "plataforma aeropuerto" "rampa" "turnos aeropuerto" "condiciones laborales"
```

**Grupo 3 — Términos de actualidad (prioridad variable):**
```
"convenio aeropuerto" "huelga" "seguridad laboral" "EMS" "contrato handling" "ERTE"
```

### 6.2. Filtros de búsqueda

Siempre se aplican estos filtros:

```bash
# Ejemplo de query compuesta:
xurl search "(sindicato OR SDP OR Barajas OR plataforma OR handling OR Aena) lang:es -is:retweet" -n 20
```

| Filtro | Valor | Razón |
|--------|-------|-------|
| Idioma | `lang:es` | Solo tweets en español |
| Retweets | `-is:retweet` | Evitamos RTs, solo contenido original |
| Respuestas | `-is:reply` | Opcional: evitar hilos existentes |
| Fecha | Últimas 24h | Solo contenido reciente |
| Calidad | Evitar spam | Se filtra por IA en el análisis |

### 6.3. Fuentes adicionales

Además de búsqueda por keywords, el agente puede:
- **Leer menciones**: `xurl mentions -n 20` — tweets que mencionan a @sindicatosdpMAD
- **Leer timeline**: `xurl timeline -n 20` — tweets de cuentas seguidas (si sigue a perfiles relevantes del sector)

---

## 7. Estrategia de Respuesta

### 7.1. Criterios de decisión (¿responder o no?)

El LLM evalúa cada tweet candidato con estas preguntas:

1. **¿Es relevante para SDP?**
   - ¿Habla del sector aeroportuario?
   - ¿Menciona a trabajadores, condiciones laborales o sindicatos?
   - ¿Ocurre en Madrid-Barajas o ámbito nacional?

2. **¿Podemos aportar valor?**
   - ¿Podemos dar información útil?
   - ¿Podemos mostrar apoyo o solidaridad?
   - ¿Podemos aclarar un malentendido?
   - ¿Podemos agradecer un gesto positivo?

3. **¿Es seguro responder?**
   - ¿El tono del tweet original es respetuoso?
   - ¿No es una trampa/provocación?
   - ¿La cuenta no es spam/bot?

4. **¿Ya hemos interactuado con este usuario hoy?**
   - Evitar responder múltiples veces al mismo usuario en un día

### 7.2. Tipos de respuesta

| Tipo | Cuándo usarlo | Ejemplo |
|------|---------------|---------|
| **Apoyo** | Compañero que expresa queja o preocupación | "Compañero, desde SDP te apoyamos. Estamos trabajando en..." |
| **Informativo** | Alguien pregunta o se queja de algo con solución | "Eso se puede solucionar hablando con tu jefe de turno. Si no, contacta con SDP." |
| **Agradecimiento** | Alguien habla bien del SDP o de los trabajadores | "Gracias por tus palabras. Trabajamos cada día por mejorar las condiciones de todos." |
| **Reivindicativo** | Debate sobre condiciones laborales | "Llevamos tiempo denunciándolo. Los trabajadores merecen..." |
| **Divulgativo** | Oportunidad de explicar la labor del SDP | "El Servicio de Dirección de Plataforma se encarga de..." |

### 7.3. Estructura de una respuesta

1. **Saludo o reconocimiento** (si procede): "Compañero", "Buenas", "Gracias por tu mensaje"
2. **Cuerpo**: Mensaje claro y directo
3. **Cierre o CTA** (si procede): "No dudes en contactarnos", "Seguiremos informando"
4. **Firma opcional**: Puede incluir ✈️ o similar

### 7.4. Límites por ejecución

- **Máximo 3 respuestas por ejecución** del cronjob
- **Máximo 1 respuesta al mismo usuario por día**
- **No responder a tweets de más de 7 días**

---

## 8. Límites y Control de Costes

### 8.1. Fichero de contadores

Se almacena en `~/.hermes/xbot-counters.json` con esta estructura:

```json
{
  "fecha": "2026-05-18",
  "busquedas_realizadas": 5,
  "respuestas_enviadas": 3,
  "busquedas_totales": 5,
  "respuestas_totales": 3,
  "historial_usuarios": {
    "@usuario1": 1,
    "@usuario2": 1
  },
  "ultima_ejecucion": "2026-05-18T14:30:00Z"
}
```

### 8.2. Parámetros configurables

| Parámetro | Valor por defecto | Descripción |
|-----------|-------------------|-------------|
| `max_busquedas_dia` | 20 | Máximo de búsquedas en X por día |
| `max_respuestas_dia` | 10 | Máximo de respuestas publicadas por día |
| `max_respuestas_ejecucion` | 3 | Máximo por cada ejecución del cronjob |
| `max_por_usuario_dia` | 1 | Máximo de respuestas al mismo usuario por día |
| `ventana_dias` | 7 | No responder a tweets de más de N días |
| `intervalo_ejecucion` | 60 | Minutos entre ejecuciones del cronjob |

### 8.3. Costes de API de X

Basado en el plan **Free** de X API:

| Acción | Límite Free | Coste |
|--------|-------------|-------|
| Posts (tweets + replies) | 1,500 / mes (≈50/día) | Gratuito |
| Búsquedas | 500 / mes (≈16/día) | Gratuito |
| Lectura de timeline | 100,000 / mes | Gratuito |

Con nuestros límites por defecto (50 búsquedas/día, 10 respuestas/día) estamos muy por debajo.

> 📌 **Nota:** Si el proyecto crece, se puede migrar al plan **Basic** ($100/mes) que permite 300,000 posts/mes y 50,000 búsquedas/mes.

### 8.4. Reinicio de contadores

El sistema verifica la fecha actual al inicio de cada ejecución. Si la fecha ha cambiado, los contadores diarios se reinician automáticamente.

---

## 9. Sistema de Almacenamiento

### 9.1. Estructura de ficheros

```
~/.hermes/
├── skills/
│   └── x-bot-sindicatosdp/
│       └── SKILL.md              ← Personalidad, estilo, criterios (sección 5)
│
├── xbot-counters.json            ← Contadores diarios (sección 8)
│
└── (la memoria de Hermes almacena
     ajustes aprendidos entre sesiones)

~/proyectos/agente-x-sindicatosdp/
├── ALCANCE_Y_DISENO.md           ← Este documento
├── scripts/
│   └── check-limits.sh           ← Script auxiliar para verificar límites
└── logs/
    └── actividad.log             ← Log de actividad del agente
```

### 9.2. El Skill `x-bot-sindicatosdp`

El skill se almacena en `~/.hermes/skills/x-bot-sindicatosdp/SKILL.md` y contiene:

```yaml
---
name: x-bot-sindicatosdp
description: "Agente autónomo X para @sindicatosdpMAD - busca y responde tweets relevantes"
version: 1.0.0
author: Jorge Martín (jODIN)
---

# x-bot-sindicatosdp

## Personalidad
... (contenido de la sección 5) ...

## Criterios de búsqueda
... (contenido de la sección 6) ...

## Estrategia de respuesta
... (contenido de la sección 7) ...

## Comportamiento
- Analiza cada tweet candidato con los criterios de la sección 7.1
- Redacta respuestas en el tono definido
- Respeta TODOS los límites de la sección 8
- NO uses Postiz para las respuestas (es para programar, no para replies en tiempo real)
- Usa SIEMPRE xurl para buscar y responder
```

Este skill se carga automáticamente cada vez que el cronjob se ejecuta.

### 9.3. Memoria de Hermes

Además del skill, Hermes tiene memoria persistente que podemos usar para:

- **Ajustes de estilo**: "Jorge prefiere respuestas más breves los fines de semana"
- **Patrones aprendidos**: "Los tweets sobre handling suelen generar buen engagement"
- **Exclusiones**: "No responder a @cuentaX porque es un troll conocido"
- **Preferencias**: "Priorizar menciones directas antes que búsquedas genéricas"

---

## 10. Configuración del Cronjob

### 10.1. Creación del cronjob

El cronjob se crea con el comando `cronjob` de Hermes:

```bash
# Parámetros:
# - schedule: cada 60 minutos (ajustable)
# - skills: ["x-bot-sindicatosdp"] (para cargar el estilo)
# - prompt: las instrucciones de ejecución
# - enabled_toolsets: ["terminal", "web", "file"] (solo las necesarias)
```

### 10.2. Prompt del cronjob

El prompt que se le pasa al agente en cada ejecución contiene las instrucciones operativas. Es auto-contenido porque los cronjobs no tienen contexto de conversación.

```markdown
Eres el agente autónomo de @sindicatosdpMAD en X (Twitter).

INSTRUCCIONES PARA ESTA EJECUCIÓN:

1. Lee el fichero de contadores: cat ~/.hermes/xbot-counters.json
   - Si la fecha es hoy y los límites no se han agotado → continúa
   - Si la fecha es anterior → reinicia contadores a 0
   - Si los límites están agotados → termina (no hagas nada)

2. Busca tweets relevantes usando xurl:
   xurl search "(sindicato OR SDP OR Barajas OR plataforma OR Aena OR handling) lang:es -is:retweet" -n 20

3. Lee las menciones a @sindicatosdpMAD:
   xurl mentions -n 10

4. Analiza cada tweet usando los criterios del skill x-bot-sindicatosdp
   (cargado automáticamente). Selecciona máximo N candidatos.

5. Para cada candidato:
   - Lee el contexto del tweet: xurl read <tweet_id>
   - Redacta una respuesta según el estilo del skill
   - Publica: xurl reply <tweet_id> "mensaje"
   - Incrementa contador_respuestas

6. Actualiza el fichero de contadores con los nuevos valores.

7. Resumen final: cuántas búsquedas hiciste, cuántas respuestas enviaste.
```

### 10.3. Variables de entorno necesarias

El cronjob necesita que `xurl` funcione correctamente. Como xurl guarda las credenciales en `~/.xurl` (fichero OAuth), no necesita variables de entorno adicionales — las credenciales persisten entre ejecuciones.

---

## 11. Plan de Implementación

### Fase 1: Preparación del entorno

| Paso | Descripción | Quién | Tiempo estimado |
|------|-------------|-------|-----------------|
| 1.1 | Instalar xurl CLI | Hermes | 1 min |
| 1.2 | Jorge crea app en X Developers | Jorge | 5 min |
| 1.3 | Configurar OAuth en xurl | Jorge + Hermes | 5 min |
| 1.4 | Verificar funcionamiento de xurl | Hermes | 2 min |

### Fase 2: Definir el skill

| Paso | Descripción | Quién | Tiempo estimado |
|------|-------------|-------|-----------------|
| 2.1 | Completar perfil de personalidad | Jorge | 10 min |
| 2.2 | Definir keywords de búsqueda exactas | Jorge | 5 min |
| 2.3 | Crear ejemplos de respuesta reales | Jorge | 5 min |
| 2.4 | Hermes crea el skill `x-bot-sindicatosdp` | Hermes | 2 min |

### Fase 3: Implementar el cronjob

| Paso | Descripción | Quién | Tiempo estimado |
|------|-------------|-------|-----------------|
| 3.1 | Crear fichero de contadores inicial | Hermes | 1 min |
| 3.2 | Registrar el cronjob en Hermes | Hermes | 2 min |
| 3.3 | Primera ejecución de prueba (manual) | Hermes | 5 min |
| 3.4 | Verificar respuestas en X | Jorge | 2 min |

### Fase 4: Ajustes y puesta en producción

| Paso | Descripción | Quién | Tiempo estimado |
|------|-------------|-------|-----------------|
| 4.1 | Revisar primeras respuestas y ajustar tono | Jorge | 10 min |
| 4.2 | Ajustar límites si es necesario | Jorge | 2 min |
| 4.3 | Activar ejecución automática (cronjob periódico) | Hermes | 1 min |
| 4.4 | Monitorizar durante 24h | Hermes/Jorge | — |

---

## 12. Mantenimiento y Monitorización

### 12.1. Tareas periódicas

| Frecuencia | Acción | Cómo |
|------------|--------|------|
| Diario | Revisar respuestas del agente | Mirar X o el log de actividad |
| Semanal | Ajustar keywords si es necesario | Editar el skill |
| Semanal | Revisar consumo de API de X | Dashboard de X Developers |
| Mensual | Actualizar ejemplos de estilo | Añadir nuevos ejemplos al skill |
| Bajo demanda | Pausar/reanudar el agente | `cronjob action=pause/resume` |

### 12.2. Logs y depuración

El agente genera un log de actividad en `~/proyectos/agente-x-sindicatosdp/logs/actividad.log` con:

```json
{"timestamp":"2026-05-18T14:30:00Z","accion":"busqueda","query":"sindicato SDP Barajas","resultados":15,"limites_restantes":{"busquedas":19,"respuestas":10}}
{"timestamp":"2026-05-18T14:31:00Z","accion":"respuesta","tweet_id":"123456789","usuario":"@compañero","mensaje":"Compañero, gracias por tu apoyo..."}
```

### 12.3. Comandos útiles para Jorge

```bash
# Ver estado del cronjob:
cronjob action=list

# Pausar el agente:
cronjob action=pause job_id=xxx

# Reanudar:
cronjob action=resume job_id=xxx

# Ejecutar manualmente una vez:
cronjob action=run job_id=xxx

# Ver contadores actuales:
cat ~/.hermes/xbot-counters.json

# Verificar auth de xurl:
xurl auth status
```

### 12.4. Escenarios de error

| Problema | Causa | Solución |
|----------|-------|----------|
| "Not authenticated" | Token OAuth expirado o no configurado | Re-ejecutar `xurl auth oauth2` |
| "429 Too Many Requests" | Límite de API de X alcanzado | Esperar al reinicio del contador de X (ventana de 15 min) |
| Respuestas incorrectas | El estilo necesita ajustes | Editar el skill con nuevos ejemplos |
| El cronjob no se ejecuta | Problema en Hermes | `cronjob action=list` para ver estado |

---

## 13. Anexos

### A. Referencias

- [xurl CLI — Documentación oficial](https://github.com/xdevplatform/xurl)
- [X API v2 — Documentación](https://developer.x.com/en/docs/twitter-api)
- [X API Rate Limits](https://developer.x.com/en/docs/twitter-api/rate-limits)
- [Hermes Agent — Documentación cronjobs](https://hermes-agent.nousresearch.com/docs)
- [X Developer Portal](https://developer.x.com/en/portal/dashboard)

### B. Glosario

| Término | Significado |
|---------|-------------|
| **SDP** | Servicio de Dirección de Plataforma |
| **Handling** | Servicios de asistencia en tierra a aeronaves |
| **Aena** | Aeropuertos Españoles y Navegación Aérea (gestor aeroportuario) |
| **xurl** | CLI oficial de X (Twitter) para interactuar con la API v2 |
| **Cronjob** | Tarea programada que se ejecuta periódicamente en Hermes |
| **Skill** | Conjunto de instrucciones reutilizables para Hermes |
| **LLM** | Large Language Model (DeepSeek en este caso) |

### C. Histórico de versiones del documento

| Versión | Fecha | Cambios |
|---------|-------|---------|
| 1.0 | 18/05/2026 | Versión inicial completa |
