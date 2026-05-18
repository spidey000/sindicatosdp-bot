# 🔌 API.md — Documentación de GetXAPI

> Endpoints, precios y ejemplos de uso de GetXAPI
> ([docs.getxapi.com](https://docs.getxapi.com/))

---

## 1. Información general

**URL base:** `https://api.getxapi.com`  
**Autenticación:** Bearer token vía header  
**Formato:** JSON  
**Precio:** Pay-per-use (sin suscripción mensual)

### Headers comunes

```python
headers = {
    "Authorization": "Bearer get-x-api-tu-key",
    "Content-Type": "application/json",
}
```

---

## 2. Endpoints disponibles

### 2.1. Búsqueda avanzada de tweets

```
GET /twitter/tweet/advanced_search
```

**Parámetros:**

| Parámetro | Tipo | Obligatorio | Descripción |
|-----------|------|:-----------:|-------------|
| `q` | string | ✅ | Query de búsqueda (sintaxis de X) |
| `product` | string | ❌ | `Latest` (por defecto) o `Top` |

**Coste:** $0.001 por llamada

**Ejemplo:**

```bash
curl -H "Authorization: Bearer $GETXAPI_KEY" \
  "https://api.getxapi.com/twitter/tweet/advanced_search?q=(huelga%20OR%20sindicato)%20lang%3Aes&product=Latest"
```

```python
import requests

headers = {"Authorization": "Bearer get-x-api-tu-key"}
params = {"q": "(huelga OR sindicato) lang:es", "product": "Latest"}
r = requests.get(
    "https://api.getxapi.com/twitter/tweet/advanced_search",
    headers=headers,
    params=params,
)
data = r.json()
```

**Respuesta (simplificada):**

```json
{
  "tweets": [
    {
      "id": "1234567890",
      "text": "Tweet contenido aquí...",
      "author": {"id": "user123", "username": "usuario"},
      "created_at": "2026-05-18T10:00:00Z",
      "mentions": ["@sindicatosdpMAD"],
      "retweet_count": 5,
      "reply_count": 2,
      "like_count": 10
    }
  ],
  "tweet_count": 20
}
```

### 2.2. Crear tweet / responder

```
POST /twitter/tweet/create
```

**Body (JSON):**

| Campo | Tipo | Obligatorio | Descripción |
|-------|------|:-----------:|-------------|
| `text` | string | ✅ | Contenido del tweet |
| `auth_token` | string | ✅ | Cookie auth_token de x.com |
| `in_reply_to_tweet_id` | string | ❌ | ID del tweet al que responder |
| `media_ids` | string[] | ❌ | IDs de medios a adjuntar |

**Coste:** $0.002 por llamada

**Ejemplo:**

```python
import requests

headers = {
    "Authorization": "Bearer get-x-api-tu-key",
    "Content-Type": "application/json",
}
payload = {
    "text": "@usuario ánimo compañero!",
    "auth_token": "tu-auth-token",
    "in_reply_to_tweet_id": "1234567890",
}
r = requests.post(
    "https://api.getxapi.com/twitter/tweet/create",
    headers=headers,
    json=payload,
)
```

### 2.3. Información de usuario

```
GET /twitter/user/info
```

**Parámetros:**

| Parámetro | Tipo | Obligatorio | Descripción |
|-----------|------|:-----------:|-------------|
| `userName` | string | ✅ | Nombre de usuario |

**Coste:** $0.001 por llamada

**Ejemplo:**

```bash
curl -H "Authorization: Bearer $GETXAPI_KEY" \
  "https://api.getxapi.com/twitter/user/info?userName=sindicatosdpMAD"
```

### 2.4. Tweets y respuestas de un usuario

```
GET /twitter/user/tweets_and_replies
```

**Parámetros:**

| Parámetro | Tipo | Obligatorio | Descripción |
|-----------|------|:-----------:|-------------|
| `userName` | string | ✅ | Nombre de usuario |

**Coste:** $0.001 por llamada

**Ejemplo:**

```bash
curl -H "Authorization: Bearer $GETXAPI_KEY" \
  "https://api.getxapi.com/twitter/user/tweets_and_replies?userName=sindicatosdpMAD"
```

---

## 3. Obtener el auth_token de X (para respuestas)

El `auth_token` es necesario solo para el endpoint de crear tweets. Se obtiene de las **cookies del navegador**:

1. Abre [x.com](https://x.com) e inicia sesión como la cuenta del bot
2. Abre herramientas de desarrollador: **F12**
3. Ve a **Application** → **Storage** → **Cookies** → **x.com**
4. Busca la cookie `auth_token`
5. Copia su valor

> ⚠️ El token expira periódicamente (semanas/meses). Cuando el bot deje de responder, renueva este token.

---

## 4. Precios y límites

| Endpoint | Precio/call | Uso diario estimado | Coste diario |
|----------|:-----------:|:-------------------:|:------------:|
| Búsqueda avanzada | $0.001 | ~5 calls | $0.005 |
| Crear tweet | $0.002 | ~3 calls | $0.006 |
| Info usuario | $0.001 | ~1 call | $0.001 |
| **Total día** | | | **~$0.012** |
| **Total mes** | | | **~$2.55** |

> 💡 **Comparativa:** La API oficial de X costaría ~$61.65/mes para el mismo volumen.
> GetXAPI es ~96% más barato.

---

## 5. Códigos de error comunes

| Código | Significado | Solución |
|--------|-------------|----------|
| 200 | OK | Todo correcto |
| 401 | No autorizado | API key inválida o caducada |
| 403 | Prohibido | Token sin permisos |
| 429 | Too Many Requests | Reducir frecuencia de llamadas |
| 500 | Error interno | Reintentar más tarde |
