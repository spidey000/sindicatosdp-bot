# 📦 INSTALL.md — Guía de instalación completa

> Cómo poner en marcha el bot @sindicatosdpMAD desde cero.

---

## Índice

1. [Requisitos previos](#1-requisitos-previos)
2. [Obtener credenciales](#2-obtener-credenciales)
3. [Configurar el proyecto](#3-configurar-el-proyecto)
4. [Probar la instalación](#4-probar-la-instalación)
5. [Configurar respuestas](#5-configurar-respuestas)
6. [Programar ejecución automática](#6-programar-ejecución-automática)
7. [Solución de problemas](#7-solución-de-problemas)

---

## 1. Requisitos previos

- **Python 3.8+** (con pip)
- **Conexión a Internet** (para llamadas a GetXAPI)
- **Cuenta de X** (la que usará el bot)
- **GetXAPI key** (ver sección 2)

### Verificar requisitos

```bash
python3 --version
pip3 --version
```

---

## 2. Obtener credenciales

### 2.1. GetXAPI key (búsquedas)

1. Ve a [docs.getxapi.com](https://docs.getxapi.com/)
2. Regístrate o inicia sesión
3. Genera una API key
4. Copia la key (empieza por `get-x-api-...`)

### 2.2. Auth token de X (respuestas — opcional hasta que quieras responder)

1. Abre [x.com](https://x.com) e inicia sesión como @sindicatosdpMAD
2. Abre herramientas de desarrollador: **F12**
3. Ve a la pestaña **Application** → **Cookies** → **x.com**
4. Busca la cookie llamada `auth_token`
5. Copia su valor

> ⚠️ Este token expira periódicamente. Si el bot deja de responder, renueva este token.

---

## 3. Configurar el proyecto

### 3.1. Estructura inicial

```bash
# Crear directorio del proyecto (si no existe)
mkdir -p ~/proyectos/agente-x-sindicatosdp

# Entrar
cd ~/proyectos/agente-x-sindicatosdp
```

### 3.2. Configurar credenciales

```bash
# Crear .env desde la plantilla
cp .env.example .env

# Editar con tus credenciales
nano .env
```

Contenido de `.env`:

```env
GETXAPI_KEY=get-x-api-tu-key-aqui
GETXAPI_BASE_URL=https://api.getxapi.com
X_AUTH_TOKEN=tu-auth-token-de-x
X_USERNAME=sindicatosdpMAD
```

### 3.3. Dependencias Python

```bash
pip3 install requests
```

O si usas virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests
```

---

## 4. Probar la instalación

### 4.1. Búsqueda general

```bash
cd ~/proyectos/agente-x-sindicatosdp
python3 scripts/search_tweets.py
```

Deberías ver un JSON con resultados.

### 4.2. Búsqueda de menciones

```bash
python3 scripts/search_tweets.py --mentions
```

### 4.3. Búsqueda personalizada

```bash
python3 scripts/search_tweets.py --query "(huelga OR sindicato) lang:es"
```

---

## 5. Configurar respuestas

Para activar las respuestas, necesitas el `X_AUTH_TOKEN` (sección 2.2).

Una vez configurado en `.env`:

```bash
# Probar respuesta (reemplaza TWEET_ID por un ID real)
python3 scripts/reply_tweet.py TWEET_ID "ánimo compañero" @usuario
```

---

## 6. Programar ejecución automática

### 6.1. Con Hermes Agent (recomendado)

Si usas Hermes Agent, el bot ya tiene un cronjob configurado:

```bash
# Ver cronjobs activos
hermes cron list

# Si necesitas crearlo de nuevo:
hermes cron create \
  --name "bot-sindicatosdp" \
  --schedule "0 * * * *" \
  --prompt "Ejecuta el bot @sindicatosdpMAD: busca tweets, filtra y responde"
```

### 6.2. Con cron del sistema (alternativa sin Hermes)

```bash
# Editar crontab
crontab -e

# Añadir línea (ejecuta cada hora):
0 * * * * cd /home/tu-usuario/proyectos/agente-x-sindicatosdp && python3 scripts/search_tweets.py >> logs/cron.log 2>&1
```

---

## 7. Solución de problemas

| Problema | Causa posible | Solución |
|----------|---------------|----------|
| `GETXAPI_KEY no encontrada` | .env no existe o mal configurado | Copia .env.example a .env y rellena |
| `X_AUTH_TOKEN no encontrado` | Token no configurado | Añade X_AUTH_TOKEN en .env |
| `status: 401` | API key inválida | Verifica tu key en getxapi.com |
| `status: 429` | Demasiadas peticiones | Espera y reduce la frecuencia |
| Sin resultados | Query muy restrictiva | Simplifica la búsqueda |
| Token expirado | auth_token caducó | Renueva desde cookies de x.com |
