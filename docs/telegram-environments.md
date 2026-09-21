# Bots de Telegram por entorno

## Un bot por entorno

Desarrollo y producción usan bots distintos. Cada bot tiene su token y **Telegram solo admite un
webhook activo por bot**: compartir token haría que las pruebas de desarrollo desviaran updates
destinados a producción.

| Entorno | Bot | Webhook |
|---|---|---|
| Desarrollo | de pruebas | dominio de dev tras el proxy, o túnel HTTPS temporal |
| Producción | público | dominio HTTPS público tras Nginx Proxy Manager |

---

## Variables por entorno

La app carga `.env.<APP_ENV>` y después `.env`; `APP_ENV` lo fija cada Compose. Dónde vive cada
fichero está en [entornos-y-despliegue.md](entornos-y-despliegue.md#2-los-ficheros-de-entorno).

```dotenv
bot_telegram_url=https://api.telegram.org/bot          # base de la API, igual en ambos
bot_telegram_token=<token del bot de este entorno>
bot_telegram_secret_token=<secreto del webhook>
bot_telegram_webhook_base_url=https://dev.tudominio.com
bot_telegram_commands=start:Inicia FitCoach,interview:Entrevista,doubts:Resuelve dudas,progress:Tu progreso
```

Dos que se confunden con facilidad:

- **`bot_telegram_url`** es el base URL de la **API de Telegram**. Mismo valor en los dos entornos.
- **`bot_telegram_webhook_base_url`** es la URL pública de **tu aplicación**, sin path. Distinta por
  entorno. El path (`/webhook/response`) lo resuelve el código desde el router.

### El secreto del webhook

Es la credencial con la que la app comprueba que quien llama es Telegram. Telegram lo devuelve en la
cabecera `X-Telegram-Bot-Api-Secret-Token` de cada update, y lo que no la traiga recibe un **403**.

Genéralo así:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Uno distinto por entorno.** Si compartieran valor, quien obtuviera el de desarrollo podría
falsificar updates contra el endpoint de producción. Admite 1-256 caracteres de `A-Z a-z 0-9 _ -`; la
app valida el formato al arrancar.

---

## Registro del webhook

**Lo hace la aplicación sola al arrancar.** No hay que ejecutar ningún `curl`.

En cada arranque, el `lifespan`:

1. Construye la URL a partir de `bot_telegram_webhook_base_url` y la ruta del router.
2. Llama a `setWebhook` con esa URL y el secreto.
3. Lee `getWebhookInfo` y comprueba que Telegram registró la que esperaba.

**Si algo de eso falla, la app no arranca.** Es intencionado: con la validación del secreto activa, un
registro fallido dejaría a Telegram entregando sin la cabecera y la app respondería 403 a todo. El bot
quedaría muerto igual, pero con el contenedor en verde. Abortando, el despliegue lo detecta y revierte.

En los logs verás:

```
[webhook 1/4] resolviendo URL de registro
[webhook 2/4] bot autenticado en Telegram
[webhook 3/4] setWebhook aceptado con secreto
[webhook 4/4] registro confirmado por Telegram
```

El paso en el que se detenga es medio diagnóstico: si no pasa del **2**, el token es inválido; del
**3**, Telegram rechazó la URL —tiene que ser HTTPS y alcanzable desde fuera—; del **4**, hay un
registro apuntando a otro sitio.

Consecuencia a tener presente: **sin una URL HTTPS pública, la app no levanta**. Para desarrollo en
local hace falta el dominio de dev o un túnel (`cloudflared`, `ngrok`). `localhost` y `http://` no
valen nunca: Telegram los rechaza.

---

## Verificación

**1. El registro es el correcto** — el secreto no lo devuelve Telegram, solo el resto:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

Mira `url`, `pending_update_count` y `last_error_message`.

**2. El candado funciona** — la única forma de comprobar el secreto desde fuera:

```bash
curl -i -X POST https://<tu-dominio>/webhook/response -d '{}' -H 'Content-Type: application/json'
```

Debe responder **403**. Si responde 200, la validación no está activa.

**3. Cada bot habla con su entorno** — `/start` al bot de desarrollo debe contestarlo
`dev-fitcoach-ia`, y al público, `fitcoach-ia`. Compruébalo en los logs de cada contenedor, no solo
por la respuesta en Telegram.
