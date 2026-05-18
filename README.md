# 🤖 @sindicatosdpMAD — Bot Autónomo de X

> **Bot autónomo para buscar y responder en X/Twitter sobre derechos laborales, aviación y sindicatos.**
> Cuenta oficial del Sindicato de Dirección de Plataforma (SDP) — Aeropuerto Adolfo Suárez Madrid-Barajas.
> Gestión a cargo de Jorge Martín, delegado de personal.

---

## 📋 Descripción

Este proyecto implementa un **agente autónomo** que opera en X (Twitter) desde la cuenta **@sindicatosdpMAD**. Busca tweets sobre temática laboral, aeroportuaria y sindical, analiza si merecen respuesta y publica respuestas con el estilo natural y humano de la cuenta.

**Características principales:**

- 🔍 **Búsqueda inteligente** en X usando GetXAPI (5 grupos temáticos)
- 🧠 **Filtrado con IA** — solo responde a tweets relevantes y seguros
- ✍️ **5 estilos de respuesta** (apoyo, reivindicativo, opinión, jurídico, denuncia)
- 📊 **Control de límites** — 20 búsquedas/día, 10 respuestas/día máximo
- 💰 **Coste mínimo** — ~$2.55/mes con GetXAPI (vs ~$61/mes con X API oficial)
- ⏱️ **Ejecución automática** vía cronjob cada 60 minutos

---

## 🏗️ Estructura del proyecto

```
agente-x-sindicatosdp/
├── README.md                      ← Este archivo
├── .env.example                   ← Plantilla de credenciales
├── .gitignore                     ← Exclusiones de Git
├── LICENSE                        ← Licencia MIT
│
├── docs/
│   ├── INSTALL.md                 ← Guía de instalación y setup
│   ├── ARCHITECTURE.md            ← Arquitectura del sistema
│   ├── API.md                     ← Documentación de GetXAPI
│   ├── CONFIGURATION.md           ← Configuración (keywords, límites, etc.)
│   ├── OPERATION.md               ← Operación diaria y monitorización
│   └── FUTURE.md                  ← Funcionalidades planificadas
│
├── scripts/
│   ├── search_tweets.py           ← Búsqueda en X vía GetXAPI ✅ Funcional
│   └── reply_tweet.py             ← Respuesta a tweets vía GetXAPI ⏳ Pte. auth_token
│
├── data/
│   ├── tweets_all.json            ← 99 tweets extraídos (análisis de estilo)
│   ├── tweets_api.json            ← Solo tweets originales
│   ├── categorizacion.json        ← Tweets categorizados por estilo
│   ├── analisis_estilo.md         ← Análisis completo de estilo de escritura
│   └── INSIGHTS_algoritmo_X.md    ← Algoritmo "For You" de X (código abierto xAI)
│
├── logs/
│   └── actividad.log              ← Registro de actividad del bot
│
└── config/
    └── limites.json               ← Configuración de límites diarios
```

---

## 🚀 Inicio rápido

```bash
# 1. Clonar el repositorio
git clone https://github.com/jorgemartin76/sindicatosdp-bot.git
cd sindicatosdp-bot

# 2. Configurar credenciales
cp .env.example .env
# Editar .env con tu GETXAPI_KEY

# 3. Probar búsqueda
python3 scripts/search_tweets.py

# 4. Probar menciones
python3 scripts/search_tweets.py --mentions
```

> 📖 Consulta [docs/INSTALL.md](docs/INSTALL.md) para la guía completa de instalación.

---

## 📊 Costes de API

| Operación | GetXAPI | X API oficial | Ahorro |
|-----------|---------|---------------|--------|
| Búsqueda | $0.001/call | $0.001/call | = |
| Respuesta | $0.002/call | $0.200/call | **100x** |
| **Coste mensual** | **~$2.55** | **~$61.65** | **~96%** |

---

## ✅ Estado del proyecto

| Componente | Estado |
|------------|--------|
| Búsqueda de tweets | ✅ Funcional (GetXAPI) |
| Filtrado por relevancia | ✅ Integrado en skill |
| Análisis de estilo (99 tweets) | ✅ Completo |
| 5 estilos de respuesta | ✅ Definidos y documentados |
| Límites diarios (20 búsquedas, 10 respuestas) | ✅ Implementados |
| Respuesta a tweets | ⏳ Pendiente auth_token de X |
| Interfaz de gestión web | 📝 Planificada (v2.0) |

---

## 📚 Documentación

| Documento | Contenido |
|-----------|-----------|
| [INSTALL.md](docs/INSTALL.md) | Setup completo del bot |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Diseño técnico y componentes |
| [API.md](docs/API.md) | Endpoints de GetXAPI y cómo usarlos |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Keywords, límites, temas configurables |
| [OPERATION.md](docs/OPERATION.md) | Cómo opera, logs y monitorización |
| [FUTURE.md](docs/FUTURE.md) | Funcionalidades planificadas (incluye interfaz de gestión) |

---

## 🔑 Requisitos

- Python 3.8+
- GetXAPI key ([docs.getxapi.com](https://docs.getxapi.com/))
- Cuenta de X: @sindicatosdpMAD (o la que quieras usar)

---

## 🧠 Créditos

- **Jorge Martín** — Delegado de personal SDP, Barajas. Contenido y dirección.
- **GetXAPI** — API de datos de X ([docs.getxapi.com](https://docs.getxapi.com/))
- Basado en análisis de 99 tweets reales y el algoritmo "For You" de X (código abierto por xAI, 2026)

---

## 📄 Licencia

Este proyecto está bajo licencia MIT. Ver [LICENSE](LICENSE) para más detalles.
