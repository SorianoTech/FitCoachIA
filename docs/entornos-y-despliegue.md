# Entorno y despliegue

Hay **un único entorno**: la imagen se construye en el propio servidor a partir del código y se
levanta con un solo `docker-compose.yml`. Este documento explica cómo encajan el workflow de CI/CD, el
`Makefile`, el Compose, el fichero de entorno y el bot de Telegram. Para el detalle de las fases del
pipeline, ver [ci-cd.md](ci-cd.md); para los comandos, [Makefile.md](Makefile.md). Para replicar este
esquema en una instancia EC2 de AWS, ver [despliegue-aws-ec2.md](despliegue-aws-ec2.md).

---

## 1. Las tres piezas

| Pieza | Responsabilidad |
|---|---|
| **`deploy.yml`** | Copia el código de la versión al servidor por SSH y lanza `make up` |
| **`Makefile`** | Resuelve **qué fichero de entorno** usar y lanza `docker compose` |
| **Compose** | Define los servicios; recibe el fichero ya resuelto |

El workflow **no sabe** dónde vive la configuración. El `Makefile` **no sabe** desplegar, solo resolver
el fichero de entorno. Por eso el mismo `make up` funciona igual lanzado a mano en el servidor que
invocado por el despliegue.

---

## 2. El fichero de entorno

| Ubicación preferida | Si no existe |
|---|---|
| `/etc/fitcoachia/dev/.env.dev` (variable `ENV_FILE` del `Makefile`) | usa `.env` de la raíz del repositorio (y avisa por consola) |

Se puede cambiar con `make up ENV_FILE=/otra/ruta`. En el servidor el fichero es de root con permisos
restringidos: **el usuario de despliegue no puede leerlo**, por eso el workflow ejecuta `sudo -n make up`
y ese usuario necesita una regla `sudoers` sin contraseña. Ver [how-to.md](how-to.md#desplegar-en-el-servidor).

La app **ya no carga `.env.<APP_ENV>`**: lee solo el fichero indicado en `FITCOACH_ENV_FILE` o, si no
está definida, `.env`. `APP_ENV` queda solo como etiqueta de observabilidad
(`deployment.environment.name`, por defecto `production`).

### Cómo llega el fichero al contenedor

```
Makefile: resuelve la ruta
    │
    ├── export FITCOACH_ENV_FILE=<ruta>      ← para el `env_file:` del compose
    └── docker compose --env-file <ruta>     ← para interpolar ${VAR} en el YAML
```

**Son dos mecanismos distintos y ambos hacen falta**, que es la confusión más común:

- `--env-file` alimenta la **interpolación** del YAML: `${POSTGRES_PASSWORD}`, `${APP_PORT}`. Se
  resuelve al leer el fichero, antes de crear nada.
- `env_file:` inyecta variables **dentro del contenedor**, para que la app las lea.

Una variable que solo esté en `env_file:` no sirve para interpolar, y al revés.

> **⚠️ Hostnames y volúmenes renombrados (migración desde un despliegue anterior).**
> Los servicios se llaman ahora `postgres`, `embedder` y (en la BD vectorial) `pgvector`. El fichero real
> `/etc/fitcoachia/dev/.env.dev` debe actualizar los hostnames: `database_url` → `@postgres:5432`,
> `vector_database_url` y `vector_database_writer_url` → `@pgvector:5432`, `embedder_url` →
> `http://embedder:8100` y `embedder_host=embedder`. Con los nombres antiguos (`postgres-dev`,
> `postgres-prod`…) la app no conectará.
> Además, los volúmenes se llaman ahora `fitcoach-postgres`: los datos de los
> volúmenes antiguos **no se migran solos**. Hay que copiarlos o renombrarlos a mano antes de `make up`
> (p. ej. `pg_dump` del Postgres antiguo y restaurar en el nuevo) o **se perderán los datos**.

---

## 3. Levantar el entorno

### Scheduler de avisos y encuestas

Los avisos de fin de ciclo y las encuestas semanales los ejecuta un scheduler dentro de la app (tarea
`asyncio` del *lifespan*), sin contenedores aparte. Ciclo de vida, tipos y cómo añadir uno nuevo en
[scheduler.md](scheduler.md); flujo de las encuestas en [encuestas-satisfaccion.md](encuestas-satisfaccion.md).

Está apagado por defecto. Para activarlo hay que poner `scheduler_enabled=true`, que activa todos los tipos de job (avisos y
encuestas); si está apagado, los jobs siguen pendientes. Las variables `training_reminders_enabled` y
`evaluation_enabled` ya no se leen: pueden quitarse de los `.env`. Activarlo solo después de migrar. Las fechas desconocidas de planes legacy no disparan
avisos masivos.

Todas las variables son opcionales (plantilla en `.env.example`):

| Variable | Defecto | Uso |
|---|---|---|
| `scheduler_enabled` | `false` | Arranca la tarea con la app |
| `scheduler_interval_seconds` | `300` (mín. 10) | Espera entre ticks, común a los dos tipos |
| `training_reminder_max_attempts` / `evaluation_max_attempts` | `5` (1-10) | Intentos antes de marcar `failed` |
| `training_reminder_retry_delay_seconds` / `evaluation_retry_delay_seconds` | `30` | Espera inicial; se duplica en cada intento |
| `training_reminder_retry_max_delay_seconds` / `evaluation_retry_max_delay_seconds` | `3600` (≥ la inicial) | Tope de la espera |
| `training_reminder_sending_timeout_seconds` / `evaluation_sending_timeout_seconds` | `120` (mín. 10) | Bloqueo (`locked_until`) del job mientras se envía |
| `training_reminder_batch_size` / `evaluation_batch_size` | `100` (1-1000) | Jobs por tick |

Un valor fuera de rango aborta el arranque de la app. `training_reminder_interval_seconds` y
`evaluation_interval_seconds` ya no se leen: pueden quedar en un `.env` antiguo sin efecto, pero conviene
quitarlos. El aviso que se entrega **al interactuar con el bot** no usa esta política: reclama el mismo job de
aviso con un bloqueo fijo de 2 minutos y su reintento a los 5 minutos (o lo que pida Telegram si es más), y de la
configuración solo toma `training_reminder_max_attempts`.

El proceso coordina todo con PostgreSQL, no usa Redis/Celery ni llama al modelo. Al apagar la app se detiene
la tarea antes de cerrar la base. `make up` lleva `--remove-orphans`, así que al desplegar
se eliminan los contenedores `training-reminders*` y `evaluation*` antiguos. La app debe tener `poll_answer` en
`allowed_updates` (lo registra al arrancar) para recibir los votos.

### Despliegue

```bash
make up          # construye y levanta app, embedder y Postgres
make app         # reconstruye y reinicia solo la API (--no-deps)
make down        # para el stack
make app-logs    # logs en directo
```

En el servidor se lanza con `sudo make up` (el fichero de entorno es de root). `make up` crea las redes
`fitcoach-internal` y `proxy-network` si no existen, construye las imágenes (`--build`) y lleva
`--remove-orphans`.

| | |
|---|---|
| Compose | `docker-compose.yml` (proyecto `fitcoach`) |
| Servicios | `fitcoach-ia`, `embedder`, `postgres` |
| Contenedores | `fitcoach-ia`, `fitcoach-embedder`, `fitcoach-postgres` |
| Volúmenes | `fitcoach-postgres` |
| Imagen | **se construye en el servidor** (`build:`); no hay imagen publicada en un registro |
| Redes | `fitcoach-internal` (interna) y `proxy-network` (solo la API, hacia Nginx Proxy Manager) |

La BD vectorial (`make vector-up`, `infra/vector-db/docker-compose.vector-db.yml`, con su `.env` en
esa carpeta) y el stack de observabilidad (`infra/observability/compose.yml`) se unen a la misma red
`fitcoach-internal`; su ciclo de vida es independiente del de la app.

---

## 4. El despliegue, paso a paso

Lo dispara `release.yml` al publicar una versión, o a mano por `workflow_dispatch` de `deploy.yml`.

```
┌─ GitHub Actions ─────────────────────────────────────────┐
│  1. Valida el formato de la versión (X.Y.Z)              │
│  2. checkout del tag de la versión                       │
│  3. rsync por SSH del repositorio → ~/fitcoachia         │
└──────────────────────────┬───────────────────────────────┘
                           │  SCRIPT_BEFORE (sesión SSH 1)
┌──────────────────────────▼───────────────────────────────┐
│  comprueba que `sudo -n` está disponible                 │
└──────────────────────────┬───────────────────────────────┘
                           │  SCRIPT_AFTER (sesión SSH 2)
┌──────────────────────────▼───────────────────────────────┐
│  sudo -n make up   (construye y levanta)                 │
│  espera a `healthy` (10 intentos × 5 s)                  │
└──────────────────────────────────────────────────────────┘
```

**`SCRIPT_BEFORE` y `SCRIPT_AFTER` son sesiones SSH distintas.** Las variables no cruzan entre ellas.

**El repositorio viaja con el despliegue** (excluye `.git`, `.github`, `tests`, `docs`, `evals` y
cualquier `.env*`), porque el servidor construye la imagen.

### Si algo falla

El workflow termina en error y muestra los últimos logs del contenedor. **No hay rollback automático**:
para volver atrás, relanza `deploy.yml` con la versión anterior, que reconstruye desde su tag. Hay una
ventana breve sin servicio en cada despliegue; el proxy devuelve 502 y Telegram reintenta los updates,
así que no se pierden mensajes.

---

## 5. Variables del entorno

| Variable | Notas |
|---|---|
| `bot_telegram_token` | token del bot (ver sección 6) |
| `bot_telegram_secret_token` | secreto del webhook |
| `bot_telegram_webhook_base_url` | dominio público HTTPS de la app |
| `POSTGRES_PASSWORD` | solo se aplica al inicializar el volumen |
| `ia_skill` | skill del entrevistador (`interviewer`, o la variante ligera `interviewer-dev`) |
| `APP_ENV` | opcional; solo etiqueta de observabilidad, por defecto `production` |

---

## 6. Bot de Telegram

El entorno usa **un único bot**, con su token y su webhook. Token, secreto y URL base se leen del fichero
de entorno real (`/etc/fitcoachia/dev/.env.dev`). **Telegram solo admite un webhook activo por bot**: no
registres el mismo token desde otro sitio (otro despliegue o tu máquina) o desviarás los updates. Al
arrancar con este bot, la app **(re)registra el webhook** en la URL de `bot_telegram_webhook_base_url`
(ver «Registro del webhook»); si el bot venía apuntando a otra URL, basta con reiniciar la app.

```dotenv
bot_telegram_url=https://api.telegram.org/bot          # base de la API de Telegram
bot_telegram_token=<token del bot>
bot_telegram_secret_token=<secreto del webhook>
bot_telegram_webhook_base_url=https://dev.fitcoach.sergiosoriano.es
bot_telegram_commands=start:Inicia FitCoach,interview:Entrevista,doubts:Resuelve dudas,progress:Tu progreso
```

Dos que se confunden con facilidad:

- **`bot_telegram_url`** es el base URL de la **API de Telegram**.
- **`bot_telegram_webhook_base_url`** es la URL pública de **tu aplicación**, sin path. El path
  (`/webhook/response`) lo resuelve el código desde el router.

### El secreto del webhook

Es la credencial con la que la app comprueba que quien llama es Telegram. Telegram lo devuelve en la
cabecera `X-Telegram-Bot-Api-Secret-Token` de cada update, y lo que no la traiga recibe un **403**.

Genéralo así:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Admite 1-256 caracteres de `A-Z a-z 0-9 _ -`; la app valida el formato al arrancar.

### Registro del webhook

**Lo hace la aplicación sola al arrancar.** No hay que ejecutar ningún `curl`. En cada arranque, el
`lifespan`:

1. Construye la URL a partir de `bot_telegram_webhook_base_url` y la ruta del router.
2. Llama a `setWebhook` con esa URL y el secreto.
3. Lee `getWebhookInfo` y comprueba que Telegram registró la que esperaba.

**Si algo de eso falla, la app no arranca.** Es intencionado: con la validación del secreto activa, un
registro fallido dejaría a Telegram entregando sin la cabecera y la app respondería 403 a todo. El bot
quedaría muerto con el contenedor en verde. Abortando, el despliegue lo detecta.

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

**Sin una URL HTTPS pública, la app no levanta.** Para probar en local hace falta un dominio público o
un túnel (`cloudflared`, `ngrok`). `localhost` y `http://` no valen nunca: Telegram los rechaza.

### Verificación

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

**3. El bot habla con tu despliegue** — `/start` debe contestarlo `fitcoach-ia`. Compruébalo en los
logs del contenedor (`make app-logs`), no solo por la respuesta en Telegram.

---

## 7. Problemas frecuentes

| Síntoma | Causa |
|---|---|
| `no existe /etc/fitcoachia/dev/.env.dev ni .env` al hacer `make up` | falta el fichero, o falta `sudo` (el fichero es de root) |
| La app no conecta a Postgres/embedder tras actualizar | el `.env` conserva los hostnames antiguos; usar `postgres`, `pgvector`, `embedder` |
| Faltan los datos tras actualizar | los volúmenes se renombraron a `fitcoach-postgres`; migrarlos a mano |
| `password authentication failed` con Postgres sano | `POSTGRES_PASSWORD` solo se aplica al **inicializar** el volumen; cambiarlo después no altera la contraseña guardada |
| El bot no recibe nada, la app en verde | webhook registrado en otro sitio: `getWebhookInfo` |
| Conflicto de nombre de contenedor al desplegar | quedó un huérfano; `make down` y `make up` usan `--remove-orphans` |
