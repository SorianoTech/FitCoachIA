# Entornos y despliegue

Cómo encajan el workflow de CI/CD, el `Makefile`, el Compose y el fichero de entorno. Para el
detalle de las fases del pipeline, ver [ci-cd.md](ci-cd.md); para los comandos, [Makefile.md](Makefile.md).
Para replicar este mismo esquema en una instancia EC2 de AWS, ver
[despliegue-aws-ec2.md](despliegue-aws-ec2.md).

---

## 1. Las tres piezas

| Pieza | Responsabilidad |
| --- | --- |
| **`deploy.yml`** | Sube los ficheros de la release a S3 y lanza por SSM `deploy-release.sh`, que orquesta el cutover con rollback |
| **`Makefile`** | Resuelve **qué fichero de entorno** usar y lanza `docker compose` |
| **Compose** | Un único `docker-compose.yml` define todos los servicios; recibe el fichero ya resuelto |

La clave está en el reparto: el workflow **no sabe** dónde vive la configuración, solo pasa una ruta.
El `Makefile` **no sabe** desplegar, solo resolver el entorno. Por eso el mismo `make prod-up`
funciona igual lanzado a mano en el servidor que invocado por el despliegue.

---

## 2. Los ficheros de entorno

Cada host tiene un solo entorno y un solo fichero de entorno, con reglas distintas:

| Entorno | Fichero | Si no existe |
| --- | --- | --- |
| **dev** | `.env` en la raíz del repositorio (`DEV_ENV_FILE` para usar otro) | **falla** y pide crearlo desde `.env.example` |
| **prod** | `/opt/fitcoachia/.env`, de root con permisos `600` | **falla**; no hay alternativa |

En producción el fichero solo lo lee root. El despliegue automático corre como root (por SSM), así
que no hace falta `sudo` ni ninguna regla `sudoers`; a mano, se lanza con `sudo`. Ver
[despliegue-aws-ec2.md](despliegue-aws-ec2.md#72-el-fichero-env).

### Cómo llega el fichero al contenedor

```
Makefile: resuelve la ruta
    │
    ├── export FITCOACH_ENV_FILE=<ruta>      ← para el `env_file:` del compose
    └── docker compose --env-file <ruta>     ← para interpolar ${VAR} en el YAML
```

**Son dos mecanismos distintos y ambos hacen falta**, que es la confusión más común:

- `--env-file` alimenta la **interpolación** del YAML: `${POSTGRES_PASSWORD}`, `${VERSION}`. Se
  resuelve al leer el fichero, antes de crear nada.
- `env_file:` inyecta variables **dentro del contenedor**, para que la app las lea.

Una variable que solo esté en `env_file:` no sirve para interpolar, y al revés.

---

## 3. Levantar cada entorno

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
| --- | --- | --- |
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
la tarea antes de cerrar la base. `make dev-up` y `make prod-up` llevan `--remove-orphans`, así que al desplegar
se eliminan los contenedores `training-reminders*` y `evaluation*` antiguos. La app debe tener `poll_answer` en
`allowed_updates` (lo registra al arrancar) para recibir los votos.

### Desarrollo

```bash
make dev-up
```

Construye las imágenes desde el código local (`--build`) y levanta todo el sistema con el `.env` de la
raíz, y te dice por consola qué fichero usa.

### Producción

```bash
cd /opt/fitcoachia
sudo VERSION=1.2.0 make prod-up
```

**No construye nada**: descarga las imágenes ya publicadas (la app con ese tag, el resto con el tag
fijado en el compose) y espera a que todos los servicios estén sanos. El `sudo` hace falta porque el
fichero de entorno es de root. Normalmente no se lanza a mano: lo hace el despliegue
([sección 4](#4-el-despliegue-paso-a-paso)).

| | dev | prod |
| --- | --- | --- |
| Imágenes | se construyen en local | se descargan de Docker Hub |
| Compose | `docker-compose.yml` | el mismo, el del tag de la release |
| Fichero de entorno | `.env` del repositorio | `/opt/fitcoachia/.env` |
| Dónde | el servidor de desarrollo o tu máquina | la instancia EC2 |

Desarrollo y producción no conviven en el mismo host: los dos usan el proyecto `fitcoach` y los
mismos nombres de contenedor, así que un segundo entorno chocaría con el primero. Esto evita además
repetir un incidente histórico en el que ambos entornos compartían alias en `proxy-network` y el bot
de producción respondía desde el contenedor de desarrollo.

---

## 4. El despliegue, paso a paso

Lo dispara `release.yml` al publicar una versión, o a mano por `workflow_dispatch`. Despliega en la
instancia EC2 de producción sin SSH y sin repositorio clonado en ella.

```
┌─ GitHub Actions (deploy.yml) ────────────────────────────────┐
│  1. Valida la versión (X.Y.Z) y hace checkout de su tag      │
│  2. Asume el rol de AWS por OIDC (environment prod-aws)      │
│  3. Lee instancia y bucket de la pila de CloudFormation      │
│  4. Sube compose, Makefile, backup-postgres.sh y             │
│     deploy-release.sh a s3://<bucket>/deploy/<versión>/      │
│  5. ssm send-command y espera el resultado (cada 15 s)       │
└──────────────────────────┬───────────────────────────────────┘
                           │  SSM, como root
┌──────────────────────────▼───────────────────────────────────┐
│  Instancia: descarga de S3 y ejecuta deploy-release.sh       │
│  1/5  contexto; /opt/fitcoachia/.env debe existir            │
│  2/5  versión en servicio → docker-compose.prev.yml          │
│  3/5  instala compose, Makefile y backup-postgres.sh         │
│  4/5  VERSION=… make prod-up  (pull + up --wait, ≤ 900 s)    │
│  5/5  borra imágenes fitcoachia/* sin uso                    │
└──────────────────────────────────────────────────────────────┘
```

Tres detalles que explican por qué está montado así:

**El tag de la release manda.** El workflow hace checkout del tag de la versión, así que el compose
desplegado lleva los tags de imagen de esa release. Por eso el rollback necesita el compose anterior
además de la versión anterior de la app.

**Si el `pull` falla, no se toca nada.** `make prod-up` descarga todas las imágenes antes de
recrear contenedores. Una imagen inexistente en el registro no tumba producción: el script restaura
el compose previo y el workflow termina en rojo.

**Sin `sudo`.** SSM ejecuta el script como root, así que el `.env` puede quedarse en `600 root` y no
hace falta ninguna regla `sudoers`.

### Si algo falla

`deploy-release.sh` vuelca el estado de los servicios y las últimas líneas de log de la app, restaura
`docker-compose.prev.yml` y lanza `make prod-up` con la versión anterior. Las imágenes antiguas se
borran solo **al final** y nunca las del compose anterior, así que la vuelta atrás siempre las tiene
en local. Si no había versión anterior (primer despliegue), el servicio queda como esté.

Compose solo recrea los servicios que cambian. Mientras se recrea la app hay una ventana breve sin
servicio: el proxy devuelve 502 y Telegram reintenta los updates, así que no se pierden mensajes.

Para repetir el despliegue a mano o revertir sin el workflow, ver
[despliegue-aws-ec2.md](despliegue-aws-ec2.md).

---

## 5. Variables por entorno

Ninguna se comparte entre dev y prod:

| Variable | Por qué difiere |
| --- | --- |
| `bot_telegram_token` | un bot distinto por entorno |
| `bot_telegram_secret_token` | un secreto por bot; compartirlo permitiría falsificar updates de prod desde dev |
| `bot_telegram_webhook_base_url` | cada entorno tiene su dominio público |
| `POSTGRES_PASSWORD` | bases de datos independientes |
| `ia_skill` | dev usa `interviewer-dev`, con tres preguntas |
| `GF_ALERT_SEVERITY` | `warning` en dev, `critical` en prod |

`DEPLOYMENT_ENVIRONMENT` (`dev` / `prod`) se fija en el fichero de entorno. De él salen la etiqueta
`deployment.environment.name` de las trazas, el datasource y las alertas de Grafana, y el sufijo del
fichero `.env.<DEPLOYMENT_ENVIRONMENT>` que carga la app.

---

## 6. Problemas frecuentes

| Síntoma | Causa |
| --- | --- |
| `no existe o no tiene permisos de acceso` al hacer `prod-up` | falta `/opt/fitcoachia/.env`, o se lanzó sin ser root |
| `POSTGRES_PASSWORD is required` en `dev-down` | el target no pasaba `--env-file`; ya corregido |
| `password authentication failed` con Postgres sano | `POSTGRES_PASSWORD` solo se aplica al **inicializar** el volumen; cambiarlo después no altera la contraseña guardada |
| El bot no recibe nada, la app en verde | webhook registrado en otro sitio: `getWebhookInfo` |
| Conflicto de nombre de contenedor al desplegar | quedó un huérfano; `make prod-down` ya usa `--remove-orphans` |
