# Puesta en marcha

## Requisitos

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker y Docker Compose, para PostgreSQL
- Un bot de Telegram y un endpoint compatible con OpenAI para probar el flujo completo

## Entornos y variables

Hay un único entorno: `docker-compose.yml` (proyecto `fitcoach`), con los servicios `fitcoach-ia`,
`embedder`, `postgres` y `pgadmin` (contenedores `fitcoach-ia`, `fitcoach-embedder`,
`fitcoach-postgres` y `fitcoach-pgadmin`; volúmenes `fitcoach-postgres` y `fitcoach-pgadmin`). La
imagen se **construye** en la máquina donde se ejecuta `make up`; no hay imagen publicada en un
registro. Los servicios comparten la red externa `fitcoach-internal`, y `proxy-network` contiene
únicamente la API publicada mediante Nginx Proxy Manager. El **`container_name`** es fijo porque de él
dependen el filtro de Alloy, el workflow de despliegue y los Proxy Hosts de Nginx Proxy Manager.

La aplicación lee solo el fichero indicado en `FITCOACH_ENV_FILE` o, si no está definida, `.env`
(las variables del sistema tienen prioridad). `APP_ENV` es opcional y solo etiqueta la observabilidad
(`deployment.environment.name`, por defecto `production`); ya no se carga `.env.<APP_ENV>`.

`make up` resuelve el fichero de entorno así:

| Fichero preferido | Si no existe |
| --- | --- |
| `/etc/fitcoachia/dev/.env.dev` (se cambia con `ENV_FILE=`) | usa `.env` en la raíz del repositorio |

Crea el fichero:

```bash
# Servidor
sudo mkdir -p /etc/fitcoachia/dev
sudo cp .env.example /etc/fitcoachia/dev/.env.dev

# O, en local, sin usar /etc/fitcoachia
cp .env.example .env
```

> **⚠️ Actualiza el fichero real `/etc/fitcoachia/dev/.env.dev`.** Los servicios del compose se
> renombraron, así que los hostnames deben ser `postgres`, `pgvector` y `embedder`: `database_url`
> (`@postgres:5432`), `vector_database_url` y `vector_database_writer_url` (`@pgvector:5432`),
> `embedder_url` (`http://embedder:8100`) y `embedder_host=embedder`. Con los nombres antiguos
> (`postgres-dev`, `postgres-prod`…) la app no conecta. Además, los **volúmenes se renombraron** a
> `fitcoach-postgres` y `fitcoach-pgadmin`: los datos de los volúmenes antiguos no se migran solos;
> cópialos o renómbralos a mano (p. ej. `pg_dump` y restauración) antes de `make up`, o se perderán.

Completa al menos estas variables:

```dotenv
bot_telegram_url=https://api.telegram.org/bot
bot_telegram_token=...
bot_telegram_secret_token=...
bot_telegram_webhook_base_url=https://dev.fitcoach.sergiosoriano.es
bot_telegram_commands=start:Inicia FitCoach,interview:Entrevista,doubts:Resuelve dudas,progress:Tu progreso

ia_base_url=...
ia_token=...
ia_model=...
ia_temperature=0.5
ia_interviewer_reasoning_effort=minimal
ia_history_window_messages=20

POSTGRES_USER=fitcoach
POSTGRES_PASSWORD=elige-una-contrasena
POSTGRES_DB=fitcoach
database_url=postgresql+asyncpg://fitcoach:elige-una-contrasena@localhost:5432/fitcoach
```

`ia_interviewer_reasoning_effort=minimal` reduce los tokens de razonamiento y la latencia de
`gpt-5-nano-2025-08-07`. Los valores admitidos son `minimal`, `low`, `medium`, `high` y `default`;
`default` omite el parámetro para proveedores compatibles con OpenAI que no implementen este
control. Cambiarlo puede afectar a la consistencia del perfil final, por lo que debe validarse el
flujo completo de entrevista.

Las dos variables del webhook son **obligatorias**; sin ellas la app no arranca.
`bot_telegram_webhook_base_url` es la URL pública de **tu app**, sin path y con HTTPS
—Telegram no acepta `http://` ni `localhost`—, mientras que `bot_telegram_url` es la base de la API
de Telegram. El bot y su webhook salen de `/etc/fitcoachia/dev/.env.dev`. Detalle en
[entornos-y-despliegue.md](entornos-y-despliegue.md#6-bot-de-telegram).

`database_url` se lee del fichero de entorno tanto con Python local (`localhost`) como en el
Compose, donde debe apuntar al servicio `postgres` (el Postgres solo está en la red `fitcoach-internal`).

## Cuota de consumo por chat

Cada chat tiene un presupuesto de tokens en una ventana móvil. Al agotarlo, la app responde con un
mensaje genérico y registra un `WARNING`, **sin llamar al modelo**. Las tres variables son
**opcionales**: sin definirlas la cuota funciona con los valores por defecto.

```dotenv
rate_limit_token_limit=150000   # punto de corte, NO techo
rate_limit_soft_ratio=0.66      # (0, 1] — fracción a la que se corta /interview
rate_limit_window_minutes=1440  # 24 h
```

Por defecto: 3 entrevistas al día por chat (~$0.015/día con `gpt-5-nano`), y un hueco de 51.000
tokens que garantiza poder terminar una entrevista ya empezada. Para pruebas interesa lo contrario
—ventanas de minutos y límites pequeños, para ver el corte sin esperar—; `.env.example` trae ambos
juegos de valores listos para copiar.

No elijas estos números a ojo: `rate_limit_token_limit` se rebasa por un turno, así que debe quedar
por debajo del techo real que no quieras cruzar. Las fórmulas de calibración, un ejemplo resuelto y
las consultas para medir tu consumo están en **[rate-limiter.md](rate-limiter.md)**.

## Ejecutar la API con Python local

1. Instala las dependencias:

   ```bash
   uv sync --all-groups
   ```

2. Levanta PostgreSQL:

   ```bash
   docker run --name fitcoach-postgres --rm -d \
     -e POSTGRES_DB=fitcoach \
     -e POSTGRES_USER=fitcoach \
     -e POSTGRES_PASSWORD=elige-una-contrasena \
     -p 5432:5432 \
     postgres:16-alpine
   ```

3. Aplica el esquema de la base de datos:

   ```bash
   uv run alembic upgrade head
   ```

4. Inicia FastAPI:

   ```bash
   uv run fastapi dev src/fitcoach/main.py --port 8000
   ```

La API queda disponible en <http://localhost:8000>. Comprueba el servicio con:

```bash
curl http://localhost:8000/health
```

Para detener PostgreSQL, ejecuta `docker stop fitcoach-postgres`.

> Ese contenedor desechable comparte nombre con el Postgres del compose (`container_name:
> fitcoach-postgres`): no lo uses en el servidor ni con el stack del compose levantado.

## Ejecutar con Docker Compose

Esta opción ejecuta PostgreSQL, el embedder, pgAdmin y la API en contenedores. El contenedor de la API
aplica automáticamente `alembic upgrade head` antes de iniciar FastAPI.

```bash
make up
```

El target crea automáticamente `fitcoach-internal` y `proxy-network` si todavía no existen, y construye
las imágenes. PostgreSQL y el embedder no publican puertos; desde otros equipos se accede a las
interfaces HTTP autorizadas mediante Nginx Proxy Manager.

Tras cambiar el código, los prompts o las skills, reconstruye solo la API sin volver a construir el
embedder ni reiniciar PostgreSQL (deben estar ya levantados con `make up`). Al arrancar también
aplica las migraciones pendientes:

```bash
make app
```

Consulta los logs:

```bash
make app-logs
```

### Consultar la base de datos con pgAdmin

El compose incluye pgAdmin (`fitcoach-pgadmin`), una interfaz web para consultar los mensajes, sesiones
y perfiles del entrevistador. No publica ningún puerto en el host: crea un Proxy Host en Nginx Proxy
Manager que apunte a `fitcoach-pgadmin`, puerto `STANDARD_HTTP_PORT` del fichero de entorno y
protocolo `http`.

Protege ese Proxy Host antes de publicarlo mediante una *Access List* de Nginx Proxy Manager y, si
es posible, una restricción por IP. Registra el servidor con host `postgres` y los valores
`POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` del fichero de entorno. Las tablas relevantes son:

- `conversation_messages`: preguntas y respuestas por chat.
- `interview_sessions`: estado y fechas de cada entrevista.
- `interviewer_profiles`: informe y perfil JSON al completar una entrevista.

Detén el stack con:

```bash
make down
```

## Desplegar en el servidor

El despliegue usa `docker-compose.yml` (proyecto `fitcoach`), la red backend externa
`fitcoach-internal` y `proxy-network` únicamente para publicar la API. `make up` crea ambas redes si
todavía no existen y **construye la imagen en el servidor** (el workflow copia el código de la versión
con rsync). Antes del primer despliegue, crea `/etc/fitcoachia/dev/.env.dev` (ver
[Entornos y variables](#entornos-y-variables)); si no existe ni ese fichero ni `.env`, `make up` falla.

`/etc/fitcoachia/dev` mantiene permisos restringidos: el usuario de despliegue (SSH) no puede
leerlo directamente. El workflow `deploy.yml` accede solo durante el comando de despliegue
mediante `sudo -n`, así que ese usuario necesita una regla `sudoers` sin contraseña:

```
# /etc/sudoers.d/fitcoach-deploy   (chmod 0440, validar con visudo -c)
<SERVER_USER> ALL=(root) NOPASSWD: /usr/bin/make, /usr/bin/test, /bin/ls
```

Para desplegar manualmente en el servidor con ese usuario restringido, antepón `sudo`:

```bash
sudo make up
```

Para volver a una versión anterior no hay rollback automático: relanza `deploy.yml` con esa versión.

### Health check del contenedor

El compose define un `healthcheck` sobre `/health` que Docker sondea **cada 5 minutos** en
régimen estable, para no llenar los logs con una petición cada pocos segundos durante toda la vida
del contenedor. Para que eso no ralentice los despliegues, lleva además `start_interval: 5s`: mientras
el contenedor arranca se sondea cada 5 segundos, así que pasa a `healthy` en cuanto responde y el
workflow de despliegue no espera 5 minutos para darlo por bueno.

```yaml
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://localhost:8000/health',timeout=2)"]
      interval: 5m
      timeout: 5s
      retries: 3
      start_period: 30s
      start_interval: 5s
```

Dos consecuencias: `start_interval` requiere **Docker Engine 25.0 o superior** en el servidor, y una
app que se cuelgue *después* de arrancar tarda hasta ~15 minutos en marcarse `unhealthy` (3 fallos ×
5 min). Los fallos de arranque, que son los que importan en un despliegue, se detectan en segundos.
El comando usa `python` porque la imagen final no trae `curl` ni `wget`.

## Pruebas y comprobaciones

## Entrevistas y perfil

El agente `interviewer` guarda el historial por chat mientras la entrevista está en progreso. Al
completar las preguntas, valida y guarda el perfil estructurado en PostgreSQL y envía un informe de
resumen por Telegram. Los mensajes posteriores invitan a generar el plan con `/train`; envía
`/interview` para reemplazar el perfil actual e iniciar una entrevista limpia.

Para probar rápidamente la generación del informe final, pon `ia_skill=interviewer-dev` en el fichero
de entorno. Esta variante solo hace tres preguntas y conserva el mismo contrato de perfil,
persistencia e informe que la skill completa (`ia_skill=interviewer`). Después de completar una
prueba, consulta el informe en pgAdmin o envía `/interview` para empezar otra.

> **Runtime de contenedores.** El `Makefile` usa `docker` por defecto, que es lo que hay en los
> runners de CI. En local, donde el runtime es podman, pasa la variable en cada invocación:
> `make vector-up DOCKER=podman`, `make up DOCKER=podman`, `make tests DOCKER=podman`.

## Plan de entrenamiento

Con la entrevista completada, `/train` genera un mesociclo de 4 semanas. Requiere dos servicios
adicionales:

- **pgVector** con el catálogo de ejercicios. Vive en su propio Compose, así que hay que levantarlo
  por separado la primera vez:

  ```bash
  make vector-up      # pgVector + pgAdmin
  make vector-logs
  make vector-down    # conserva el volumen con la carga inicial
  ```

- **`embedder`**, que vectoriza la consulta con el mismo modelo que el corpus. Lo construye el
  propio `make up`. La primera build descarga el modelo y tarda varios minutos; las siguientes
  usan caché.

Ver [vector-db.md](vector-db.md) para el esquema, el modelo de embeddings y el rol de solo lectura,
y [trainer-agent.md](trainer-agent.md) para el comportamiento del agente.

Para pruebas, `ia_trainer_skill=trainer-dev` (en el fichero de entorno) desarrolla bien la semana 1 y
deriva las otras tres, con un máximo de 3 ejercicios por día. Mantiene intactas las comprobaciones
que importan (ids del catálogo, 4 semanas, días comprometidos), así que sirve para probar el flujo
completo sin gastar 4096 tokens por iteración.

Repetir `/train` **no** sobrescribe el plan: crea la versión N+1 en `training_plans`. Mientras haya
un plan activo, los mensajes sin comando los responde el entrenador sobre ese plan.
Cada consulta recupera de PostgreSQL el plan más reciente, el perfil disponible y el historial del
entrenador, sin consultar pgVector ni el embedder. Es un modo de solo lectura: explica el plan, pero
no sustituye ejercicios ni guarda ajustes.

### Variables de entorno del entrenador

```dotenv
# Agente 2 (entrenador). El mesociclo completo no cabe en ia_max_tokens.
ia_trainer_skill=trainer
ia_trainer_max_tokens=4096
ia_trainer_history_window_messages=10
# Ejercicios recuperados de la BD vectorial por grupo muscular.
ia_rag_top_k=8

POSTGRES_USER=fitcoach
POSTGRES_PASSWORD=...
POSTGRES_HOST=postgres
POSTGRES_DB=fitcoach
POSTGRES_PORT=5432

# Base de datos vectorial (catalogo de ejercicios). Solo lectura: ver
# infra/vector-db/ddl/002_2026-09-21_readonly-role.sql. Levantala con `make vector-up`.
VECTOR_DB_USER=fitcoach_ro
VECTOR_DB_PASSWORD=...
VECTOR_DB_HOST=pgvector
VECTOR_DB_NAME=fitcoach
VECTOR_DB_PORT=5433

PGADMIN_DEFAULT_EMAIL=admin@admin.com
PGADMIN_DEFAULT_PASSWORD=admin
PGADMIN_PORT=8010
STANDARD_HTTP_PORT=80

# Servicio de embeddings (infra/embedder). DEBE usar el mismo modelo que el
# corpus: all-MiniLM-L6-v2, 384 dimensiones.
embedder_port=8100
embedder_timeout_seconds=10
```

La aplicación no arranca si falta `vector_db_url` o `embedder_url`.

### Avisos y encuestas semanales

Los avisos y las encuestas los ejecuta el scheduler de la app y están desactivados por defecto. Para
probarlos, añadir al fichero de entorno (plantilla completa en `.env.example`):

```dotenv
scheduler_enabled=true
# Ticks cada 10 s para no esperar en pruebas manuales (mínimo 10).
scheduler_interval_seconds=10
```

Las encuestas vencen a los 7/14/21/28 días del inicio del ciclo; para probarlas sin esperar,
mover hacia atrás `training_mesocycles.started_at` y adelantar `job_execution.execution_date` de los jobs
`evaluation_poll` pendientes del ciclo en la base de datos. Detalle en [scheduler.md](scheduler.md),
[entornos-y-despliegue.md](entornos-y-despliegue.md#scheduler-de-avisos-y-encuestas) y
[trainer-agent.md](trainer-agent.md#encuestas-semanales-de-satisfacción).

```bash
# Suite completa con cobertura mínima del 80 %
uv run pytest tests --cov=src/fitcoach --cov-fail-under=80

# Solo unitarias (sin Docker, sin red, sin LLM)
uv run pytest tests/unit_test --no-cov

# Integración: necesita el entorno de tests levantado (make tests lo hace por ti).
# Levanta PostgreSQL, pgVector con un corpus mínimo y un stub de Telegram/LLM/embedder.
uv run pytest tests/it --no-cov

# Calidad y tipos
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```
