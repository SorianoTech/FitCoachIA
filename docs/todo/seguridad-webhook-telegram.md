# Pendiente: autenticar el webhook de Telegram

Rescatado del plan de métricas custom (descartado el 21-09-2026); no tenía relación con métricas.

## El problema

**`/webhook/response` no verifica que el emisor sea Telegram**
([webhook.py:53-61](../../src/fitcoach/api/webhook.py#L53-L61)). No hay comprobación del header
`X-Telegram-Bot-Api-Secret-Token` —soportado por `setWebhook(secret_token=...)`— ni de origen.

Cualquiera que conozca la URL puede enviar un `Update` con un `chat_id` arbitrario y disparar
`ConversationService.handle_update`: gasto de tokens y coste del LLM, escritura en Postgres, y envío
de mensajes del bot a ese `chat_id`, todo atribuido a una conversación que nunca ocurrió.

## Las dos credenciales, que no hay que confundir

| Dirección | Credencial | Dónde se valida | Estado |
|---|---|---|---|
| App → Telegram | **bot token** (en la URL de la Bot API) | Telegram | ya existe: `bot_telegram_token` |
| Telegram → App | **webhook secret** (cabecera) | nuestro endpoint | **falta** |

Son secretos distintos y en direcciones opuestas. Lo que falta es el segundo.

**Un secreto por bot.** El `secret_token` se registra en el `setWebhook` de cada bot y Telegram solo
lo envía en los updates de ese bot. Como ya hay un bot por entorno, cada uno lleva el suyo, y deben
ser **distintos**: si compartieran valor, quien obtuviera el de desarrollo podría falsificar updates
contra el endpoint de producción.

Generarlo:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Telegram admite 1-256 caracteres del conjunto `A-Z a-z 0-9 _ -`.

## Dónde vive

Junto al resto de credenciales, en los mismos ficheros que ya usa el proyecto: `.env.dev` / `.env.prod`
en la raíz del repositorio para desarrollo local, y `/etc/fitcoachia/<entorno>/.env.<entorno>` en el
servidor, con sus permisos restringidos y la regla `sudoers` que ya existe. Una sola forma de
gestionar secretos, sin introducir Docker secrets en paralelo.

```dotenv
bot_telegram_secret_token=<valor distinto por entorno>
bot_telegram_webhook_base_url=https://api.tudominio.com
```

## 1. Configuración

`src/fitcoach/infrastructure/config/settings.py`, en `Settings`:

```python
from pydantic import SecretStr

    bot_telegram_token: SecretStr
    bot_telegram_secret_token: SecretStr
    bot_telegram_webhook_base_url: str
```

Tres notas:

- `SecretStr` evita que el valor aparezca al imprimir la configuración o en una traza de error.
  **Decidido: el bot token también pasa a `SecretStr`**, que hoy va en claro. El único punto de uso
  en producción es [telegram_bot.py:23](../../src/fitcoach/infrastructure/bot/telegram_bot.py#L23),
  que queda así:

  ```python
  return Bot(
      base_url=get_settings().bot_telegram_url,
      token=get_settings().bot_telegram_token.get_secret_value(),
  )
  ```

  Las fixtures de los tests que pasan `bot_telegram_token="test-token"` siguen funcionando sin
  tocarlas: pydantic convierte la cadena a `SecretStr`.
- **`bot_telegram_webhook_base_url` es nueva y hace falta.** La app no conoce su propia URL pública:
  `bot_telegram_url` es el *base URL de la API de Telegram* (`https://api.telegram.org/bot`), pese a
  lo que dice su comentario en el código. Sin esta variable no se puede autorregistrar el webhook.
- Validar el formato del secreto en un `field_validator` para fallar al arrancar y no en el primer
  update rechazado.

## 2. La dependencia de validación

`src/fitcoach/api/security.py`:

```python
import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from fitcoach.infrastructure.config.settings import Settings, get_settings


async def verify_telegram_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.bot_telegram_secret_token.get_secret_value().encode()
    received = (x_telegram_bot_api_secret_token or "").encode()
    # compare_digest: tiempo constante, no se deduce el secreto midiendo respuestas.
    if not received or not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
```

La comparación va en **bytes**: `hmac.compare_digest` con `str` lanza `TypeError` si la cabecera trae
caracteres no ASCII, y eso acabaría en un 500 en vez de un 403.

Y en `webhook.py`:

```python
@webhook.post(
    "/response",
    dependencies=[Depends(verify_telegram_secret)],
    include_in_schema=False,
)
async def telegram_webhook(...)
```

`include_in_schema=False` saca la ruta de `/docs`, que hoy está publicada.

## 3. Registro automático del webhook

Decisión tomada: la app lo registra al arrancar, en lugar del `curl` manual que documenta
[telegram-environments.md](../telegram-environments.md). Se autocorrige en cada despliegue y detecta
el caso «Telegram apunta a otro sitio», que es un fallo real ya sufrido.

**Decidido: si no se puede registrar el webhook con su secreto, la app no arranca.** Coherente con el
resto del `lifespan`, que ya hace fail fast con la configuración.

El motivo no es purismo. Con la validación del secreto activa, un `set_webhook` fallido deja a
Telegram entregando con el registro **anterior**, sin la cabecera, así que la dependencia devolvería
403 a todos los updates. El bot queda muerto igual; la única diferencia es si se nota. Abortando el
arranque, el health check del despliegue lo detecta y dispara el rollback. Sin abortar, tendrías un
contenedor sano y un bot mudo, que es el modo de fallo más caro de diagnosticar — y ya ocurrió una
vez en este proyecto.

En el `lifespan` de `main.py`, tras `configure_telemetry`:

`bot_telegram_webhook_base_url` es solo el **origen público** (`https://api.tudominio.com`), no la URL
completa. El path se obtiene del propio router con `url_path_for`, que resuelve por el nombre de la
función del endpoint: así hay una sola fuente de verdad y cambiar el `prefix` o el decorador no
obliga a sincronizar nada.

Si el path viviera en la configuración, un cambio de ruta olvidado en el `.env` registraría la URL
antigua, la comprobación de abajo compararía ese valor contra sí mismo —coincidirían— y la app
arrancaría sana mientras Telegram hace POST contra un 404.

```python
    path = app.url_path_for("telegram_webhook")  # /webhook/response
    expected_url = f"{settings.bot_telegram_webhook_base_url.rstrip('/')}{path}"
    bot = await get_bot()
    await bot.set_webhook(
        url=expected_url,
        secret_token=settings.bot_telegram_secret_token.get_secret_value(),
        allowed_updates=["message", "edited_message"],
        drop_pending_updates=False,
    )
    info = await bot.get_webhook_info()
    if info.url != expected_url:
        raise RuntimeError(f"webhook registrado en {info.url}, esperado {expected_url}")
    if info.last_error_message:
        logger.warning(f"ultimo error de entrega de Telegram: {info.last_error_message}")
```

- Sin `try`: cualquier excepción de `set_webhook` aborta el arranque, que es lo que se busca.
- `allowed_updates` limitado a lo que se procesa: hoy `message` y `edited_message`.
- `drop_pending_updates=False`, para no perder mensajes de un reinicio.
- `last_error_message` es **WARNING, no fallo**: describe entregas pasadas, normalmente de la ventana
  de caída del despliegue anterior, y no impide que el bot funcione ahora.

**Consecuencia aceptada**: la app no arranca si la API de Telegram está caída. A cambio, un registro
fallido nunca pasa desapercibido.

## 4. Alertar cuando el webhook no está donde debe

Sí es posible con lo que hay montado, aunque **no con métricas**: el plan que las introducía se
descartó. La vía es el log, que ya llega a Loki vía Alloy, y Grafana admite reglas de alerta sobre
Loki.

Regla sobre los ERROR anteriores, en la carpeta «FitCoachIA» de
`infra/observability/config/grafana/provisioning/alerting/rules.yml`:

```logql
{service_name="fitcoach-ia"} |= "webhook mismatch" or "webhook delivery error"
```

**Limitación importante**: eso solo se evalúa **al arrancar la app**. Si alguien repunta el webhook
con el servicio en marcha, no se detecta hasta el siguiente reinicio — que es exactamente el modo de
fallo que hubo (la app sana, sin recibir un solo `POST /webhook/response`).

Para cobertura continua hacen falta dos cosas más, en este orden de coste:

1. **Tarea periódica** que llame a `getWebhookInfo` cada N minutos y registre el mismo ERROR. Cubre
   el caso completo y se apoya en la misma alerta de Loki.
2. **Alerta por ausencia de tráfico**: `absent_over_time` sobre la métrica HTTP del webhook. Hoy no
   existe esa métrica; vendría del instrumentor de FastAPI, que requiere el `MeterProvider` que se
   revirtió. Es la señal más honesta —detecta que no llegan updates, sea cual sea la causa— pero
   depende de reintroducir métricas.

## 5. Tests

`tests/unit_test/test_webhook_security.py`, sobre una app mínima y no sobre `main`, para no arrastrar
el `lifespan`:

- **KO** — sin cabecera → 403.
- **KO** — secreto incorrecto → 403.
- **KO** — cabecera con caracteres no ASCII → 403, no 500. Es la regresión de comparar en bytes.
- **OK** — secreto correcto → 200.

Y uno de regresión sobre el endpoint real: que `/webhook/response` **rechaza** un update válido sin
la cabecera. Sin él, alguien podría quitar la dependencia y los tests actuales seguirían pasando.

## 6. Fuera de alcance — autorización de usuario

**No entra en este trabajo.** Se aborda por separado; queda anotado para no perderlo de vista.

El `secret_token` es **autenticación del emisor**: demuestra que la petición viene de Telegram. No
dice nada sobre **quién** es el usuario ni si debe ser atendido.

Cualquiera que encuentre el bot en Telegram le escribe, y Telegram entrega ese update con el secreto
correcto, legítimamente. Hoy `handle_update` procesa todo lo que llega: **no hay un solo filtro por
usuario en el código**. Eso significa entrevista completa, filas en Postgres y consumo del LLM
pagado, para cualquier desconocido.

Conviene no confundirlo con el `filters.ChatType.PRIVATE` de la guía de referencia: eso restringe el
**tipo de chat** —que no responda en grupos— no la identidad de quien escribe.

Tres vías, de menor a mayor coste:

**A. Lista blanca de `telegram_user_id`.** Lo razonable para un bot privado. Una variable de entorno
con los ids permitidos, comprobada en `handle_update` antes de procesar, y un mensaje de cortesía a
quien no esté. El id ya se extrae hoy (`telegram_user_id(message)`), así que es un `if`.

**B. Cupo por usuario.** Si el bot llega a ser público, la lista blanca no sirve y hace falta limitar
el consumo. `token_usage` ya registra el gasto por `chat_id` y tiene índice `(chat_id, created_at)`,
así que un tope diario es una consulta: sumar tokens del día y rechazar por encima del umbral. Es
lo que hace falta para acotar el coste, y no depende de ningún componente nuevo.

**C. Nada**, que es el estado actual.

La decisión depende de si el bot va a ser privado o abierto. Mientras siga siendo del TFM, A es
suficiente y cuesta veinte líneas. Si se publica, hace falta B, y entonces conviene decidir también
qué se hace con los datos de esas conversaciones.

## 7. Defecto relacionado, de menor gravedad

`parse_update` solo captura `ValueError` (JSON malformado), pero `Update.de_json` también lanza
`TypeError` si falta `update_id` y `KeyError` si un `message` viene incompleto. Verificado contra
`python-telegram-bot` 22.8:

```
Update.de_json({})                            -> TypeError: falta 'update_id'
Update.de_json({"message": {"chat": {...}}})  -> KeyError: 'date'
```

Ninguna está capturada, así que un cuerpo con JSON válido pero incompleto devuelve un 500. Eso rompe
la invariante que el propio código documenta —siempre responder 2xx para que Telegram no reintente en
bucle—, porque el fallo ocurre en la resolución del `Depends`, antes de `handle_update`.

Con la validación del secreto, este 500 deja de ser alcanzable por cualquiera, pero conviene
capturarlo igual.

## Anexo — la opción B, que NO se implementa ahora

La guía de referencia propone además migrar a `Application` de PTB con `update_queue.put`, de modo
que el endpoint responda 200 de inmediato y el turno se procese en segundo plano.

**Es ortogonal a la autenticación y a la autorización.** La validación del secreto es una dependencia
de FastAPI que corre antes de nada, y la lista blanca es un `if` al entrar en el servicio; ninguna de
las dos cambia según se procese el update dentro de la petición o en una cola. La guía las presenta
juntas porque es un tutorial que monta la pila entera desde cero, no porque una requiera la otra.

**No aporta seguridad**, y el coste es alto: hoy `ConversationService.handle_update` se ejecuta
dentro de la petición y nunca propaga excepciones, precisamente para garantizar el 2xx. Migrar
supone reescribir el servicio como handlers de PTB y cambiar cómo se propagan y observan los errores.

El argumento real a su favor es otro: si un turno tarda más que el timeout de Telegram, hoy se
reintenta el update y se procesa dos veces. Si eso llega a ocurrir, esta migración es la solución —
pero entonces es un cambio de arquitectura con su propia justificación, no una tarea de seguridad.
