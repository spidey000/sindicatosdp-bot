# Despliegue con Docker y Caddy Auth

## 1. Preparar `.env`

```bash
cp .env.example .env
```

Completa al menos:

```env
GETXAPI_KEY=...
GETXAPI_BASE_URL=https://api.getxapi.com
X_AUTH_TOKEN=...
X_USERNAME=sindicatosdpMAD
PANEL_PORT=8080
CADDY_AUTH_USER=gg0099
CADDY_AUTH_HASH=...
REQUIRE_PROXY_AUTH_HEADER=true
REMOTE_USER_HEADER=Remote-User
```

## 2. Generar contraseña para Caddy Auth

```bash
docker run --rm -it caddy:2 caddy hash-password
```

Pega el resultado en `.env` como `CADDY_AUTH_HASH`. No pegues la contraseña en claro.

Importante: los hashes bcrypt contienen `$`. En `.env`, pon el hash entre comillas simples para que Docker Compose no intente interpolarlo:

```env
CADDY_AUTH_HASH='$2a$14$...'
```

## 3. Levantar servicios

```bash
docker compose up -d --build
```

Accede a:

```text
http://IP_DEL_SERVIDOR:8080
```

## 4. Servicios

```text
caddy   único servicio expuesto al host
panel   FastAPI interno, no expone puerto público
worker  scheduler interno, no expone puerto público
```

## 5. Volúmenes persistentes

```text
./config:/app/config
./data:/app/data
./logs:/app/logs
```

## 6. Seguridad

- Usar `PANEL_PORT` solo en LAN/VPN/Tailscale si no hay HTTPS.
- Si se expone a internet, usar dominio y TLS real.
- Mantener `REQUIRE_PROXY_AUTH_HEADER=true` para bloquear acceso directo al panel si no pasa por Caddy.
- No publicar `.env`.
- No activar `auto_reply_enabled` ni desactivar `dry_run` hasta haber probado la cola.

## 7. Comandos útiles

```bash
docker compose logs -f panel worker caddy
docker compose run --rm worker python scripts/run_bot.py --once
docker compose down
docker compose up -d --build
```

## 8. Publicación real

Para que publique aprobadas:

1. Revisa candidatos en `/cola`.
2. Aprueba manualmente desde `/candidatos/{id}`.
3. En `/limites`, desactiva `dry_run`, mantén `manual_approval_required` y activa `auto_reply_enabled`.
4. Verifica `GETXAPI_KEY` y `X_AUTH_TOKEN` en `/secretos`.
