# 🚀 FUTURE.md — Funcionalidades planificadas

> Este documento describe las funcionalidades implementadas y las planificadas para el futuro del bot @sindicatosdpMAD.

---

## 📋 Estado actual (v1.0) — Implementado

### Búsqueda de tweets
- [x] Búsqueda por keywords vía GetXAPI
- [x] Búsqueda de menciones a @sindicatosdpMAD
- [x] Monitorización de cuentas clave
- [x] Filtros de idioma (español) y retweets

### Análisis de estilo
- [x] Extracción y análisis de 99 tweets reales
- [x] Categorización en 5 estilos de respuesta
- [x] Definición de personalidad (20 años en torre, delegado SDP)
- [x] Reglas de estilo (sin hashtags, sin emojis, tono humano)

### Límites y control
- [x] Contadores diarios (20 búsquedas, 10 respuestas)
- [x] Reinicio automático de contadores
- [x] Historial de usuarios respondidos

### Respuestas
- [x] Script de respuesta vía GetXAPI
- [x] Integración con auth_token de X
- [ ] **Pendiente:** auth_token funcional (esperando token del usuario)

### Documentación
- [x] README completo
- [x] Guía de instalación
- [x] Arquitectura del sistema
- [x] API endpoints y precios
- [x] Configuración (keywords, límites)
- [x] Operación y mantenimiento
- [x] Futuras funcionalidades (este documento)
- [x] Análisis de estilo de 99 tweets
- [x] Algoritmo "For You" de X

---

## 🗺️ Futuro (v2.0+)

### Prioridad alta

#### 🖥️ Interfaz de gestión web

Una interfaz web auto-contenida para gestionar el bot sin depender de Hermes Agent:

```
┌──────────────────────────────────────┐
│  Gestión @sindicatosdpMAD  v2.0      │
├──────────────────────────────────────┤
│  📊 Dashboard                         │
│  ├─ Búsquedas hoy: 12/20             │
│  ├─ Respuestas hoy: 3/10             │
│  ├─ Coste del día: $0.008            │
│  └─ Última ejecución: hace 23 min    │
│                                       │
│  🔍 Keywords                          │
│  ├─ [huelga, aeropuerto, ...]        │
│  └─ [+ Añadir keyword]               │
│                                       │
│  👥 Cuentas monitorizadas             │
│  ├─ @USCAnet, @controladores...       │
│  └─ [+ Añadir cuenta]                │
│                                       │
│  ⏰ Programación                      │
│  ├─ Intervalo: cada 60 min           │
│  ├─ Máx búsquedas/día: 20            │
│  └─ Máx respuestas/día: 10           │
│                                       │
│  📜 Historial                        │
│  ├─ Últimas respuestas enviadas      │
│  └─ Últimos resultados de búsqueda   │
│                                       │
│  ⚙️ Estado del sistema                │
│  ├─ Conexión GetXAPI: ✅              │
│  └─ Auth token X: ✅ (válido)         │
└──────────────────────────────────────┘
```

**Tecnología propuesta:** Flask/FastAPI (Python) + HTML/JS simple. Sin frameworks JS pesados.
**Estado:** No iniciado.

#### 📊 Dashboard de estadísticas

- Gráfico de respuestas por día/semana/mes
- Coste acumulado
- Tweets más exitosos (engagement)
- Temáticas más respondidas

### Prioridad media

#### 📝 Publicación de tweets originales

Además de responder, que el bot pueda publicar tweets propios sobre:
- Jurisprudencia laboral reciente
- Comparativas Europa vs España
- Denuncias de vulneraciones de derechos

#### 🤖 Múltiples estilos automáticos

Que el bot varíe automáticamente entre los 5 estilos según:
- El tono del tweet original
- La hora del día
- El tipo de contenido detectado

#### 🔄 Monitorización de hilos

Que el bot pueda seguir una conversación y responder múltiples veces en un hilo si es relevante.

### Prioridad baja

#### 🌐 APIs adicionales

- Integración con fuentes de jurisprudencia (CENDOJ)
- Notificaciones push al móvil
- Historial exportable a PDF

#### 📱 App móvil simple

- Versión PWA de la interfaz de gestión
- Notificaciones de actividad del bot
- Aprobación manual de respuestas antes de publicar

#### 🤝 Multi-cuenta

- Gestionar múltiples cuentas sindicales desde la misma interfaz
- Compartir configuración entre cuentas

---

## 📐 Diseño conceptual de la interfaz de gestión

### Stack propuesto

| Componente | Tecnología | Razón |
|-----------|------------|-------|
| Backend | Flask (Python) | Ya tenemos Python, mínimo stack |
| Frontend | HTML + CSS + vanilla JS | Sin dependencias, auto-contenido |
| Datos | JSON files | Ya tenemos la estructura |
| Auth | Básica (contraseña única) | Suficiente para uso personal |

### Estructura de ficheros propuesta

```
sindicatosdp-bot/
├── web/
│   ├── app.py              ← Servidor Flask
│   ├── templates/
│   │   ├── index.html      ← Dashboard
│   │   ├── keywords.html   ← Gestión keywords
│   │   ├── limits.html     ← Configuración límites
│   │   └── logs.html       ← Historial/logs
│   └── static/
│       └── style.css
├── scripts/                ← (existente)
├── docs/                   ← (existente)
└── run_web.sh             ← Script para arrancar la interfaz
```

### Mockup de la pantalla principal

```
╔══════════════════════════════════════════════╗
║  🛩️ @sindicatosdpMAD — Panel de control      ║
╠══════════════════════════════════════════════╣
║                                              ║
║  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       ║
║  │  12  │ │   3  │ │$0.008│ │  ✅  │       ║
║  │Búsqu.│ │Resp. │ │Coste │ │Salud │       ║
║  └──────┘ └──────┘ └──────┘ └──────┘       ║
║                                              ║
║  📋 Últimas respuestas                       ║
║  ┌─────────────────────────────────────┐    ║
║  │ hace 23m: @usuario — "ánimo..."     │    ║
║  │ hace 1h: @otro — "totalmente..."   │    ║
║  └─────────────────────────────────────┘    ║
║                                              ║
║  ⏰ Próxima ejecución: en 37 min             ║
║  [▶ Ejecutar ahora] [⏸ Pausar] [⚙ Config]  ║
║                                              ║
╚══════════════════════════════════════════════╝
```

---

## 🎯 Hitos

| Hito | Versión | Fecha estimada | Estado |
|------|:-------:|:--------------:|:------:|
| Búsquedas funcionales | v1.0 | May 2026 | ✅ |
| Respuestas funcionales | v1.1 | May 2026 | ⏳ Pte auth_token |
| Documentación completa | v1.0 | May 2026 | ✅ |
| Repositorio GitHub | v1.0 | May 2026 | ✅ |
| Interfaz de gestión web | v2.0 | Jun 2026 | 📝 Planificado |
| Publicación tweets originales | v2.1 | Jul 2026 | 💡 Idea |
| Dashboard de estadísticas | v2.2 | Jul 2026 | 💡 Idea |
