# Levantar el entorno de desarrollo

## Requisitos

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker y Docker Compose, para PostgreSQL
- Un bot de Telegram y un endpoint compatible con OpenAI para probar el flujo completo

## Entornos y variables

Todo el sistema está en un único [`docker-compose.yml`](../docker-compose.yml) (proyecto `fitcoach`):
la app, el embedder, las dos bases de datos, pgAdmin, la observabilidad y Nginx Proxy Manager. Cada
host tiene **un solo entorno**, y lo que distingue desarrollo de producción es el fichero de entorno,
no el Compose:

| Servicio | Contenedor | Para qué |
| --- | --- | --- |
| `fitcoach-ia` | `fitcoach-ia` | API, bot y scheduler |
| `postgres` | `fitcoach-postgres` | Base de la aplicación, volumen `fitcoach-postgres` |
| `pgvector` | `pgvector` | Catálogo de ejercicios |
| `embedder` | `fitcoach-embedder` | Embeddings de las consultas |
| `pgadmin` | `pgadmin` | Administración de las dos bases |

El **`container_name`** es fijo porque de él dependen el filtro de Alloy, el despliegue y los Proxy
Hosts de Nginx Proxy Manager. Además hace imposible tener dos contenedores del mismo rol en un host:
un duplicado choca de nombre y falla en alto.

`DEPLOYMENT_ENVIRONMENT` (`dev` o `prod`) se fija en el fichero de entorno. La aplicación carga
`.env.<DEPLOYMENT_ENVIRONMENT>` si existe y después `.env`; las variables del sistema tienen prioridad.

| Entorno | Fichero que leen los `make` | Detalle |
| --- | --- | --- |
| Desarrollo | `.env` en la raíz del repositorio (`DEV_ENV_FILE` para usar otro) | [Makefile.md](Makefile.md#cómo-se-resuelve-el-fichero-de-entorno) |
| Producción | `/opt/fitcoachia/.env`, de root con permisos `600` | [despliegue-aws-ec2.md](despliegue-aws-ec2.md#72-el-fichero-env) |

Para desarrollo, parte de la plantilla:

```bash
cp .env.example .env
```

Completa al menos estas variables. En desarrollo, con el bot y el endpoint de desarrollo:

```dotenv
DEPLOYMENT_ENVIRONMENT=dev
bot_telegram_url=https://api.telegram.org/bot
bot_telegram_token=...
bot_telegram_secret_token=...
bot_telegram_webhook_base_url=https://dev.tudominio.com
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

Las dos variables del webhook son **obligatorias y distintas por entorno**; sin ellas la app no
arranca. `bot_telegram_webhook_base_url` es la URL pública de **tu app**, sin path y con HTTPS
—Telegram no acepta `http://` ni `localhost`—, mientras que `bot_telegram_url` es la base de la API
de Telegram y vale igual en los dos entornos. Detalle en
[telegram-environments.md](telegram-environments.md).

`database_url` debe apuntar al host que ve la API: `localhost` si la ejecutas con Python local, como
en el ejemplo, y `postgres` (el servicio del Compose) si corre en Docker, como en `.env.example`. Lo
mismo vale para `vector_database_url` (`pgvector`) y `embedder_url` (`embedder`).

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
tokens que garantiza poder terminar una entrevista ya empezada. En desarrollo interesa lo contrario
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

> Ese contenedor desechable comparte nombre con el Postgres del Compose (`container_name:
> fitcoach-postgres`): no lo uses a la vez que `make dev-up`, ni en el servidor.

## Ejecutar desarrollo con Docker Compose

Esta opción construye las imágenes desde el código local y levanta todo el sistema en contenedores.
El contenedor de la API aplica automáticamente `alembic upgrade head` antes de iniciar FastAPI.

```bash
make dev-up
```

Las redes las crea el propio Compose. Solo se publican en el host `APP_PORT` (la API),
`VECTOR_PORT` (pgVector) y `PGADMIN_PORT` (pgAdmin); PostgreSQL y el embedder solo se ven dentro de
la red del Compose. Desde otros equipos se entra por Nginx Proxy Manager.

Tras cambiar el código, los prompts o las skills, reconstruye solo la API sin volver a construir el
embedder ni reiniciar PostgreSQL (deben estar ya levantados con `make dev-up`). Al arrancar también
aplica las migraciones pendientes:

```bash
make dev-app
```

Consulta los logs de la API:

```bash
make dev-logs
```

### Consultar las bases de datos con pgAdmin

pgAdmin queda en `http://localhost:<PGADMIN_PORT>` (8010 en `.env.example`), con
`PGADMIN_DEFAULT_EMAIL` y `PGADMIN_DEFAULT_PASSWORD`. En un servidor no se publica en internet: se
usa por túnel ([despliegue-aws-ec2.md](despliegue-aws-ec2.md#63-túneles-a-paneles-internos)).

Para registrar las bases, usa los nombres de servicio y el puerto interno `5432`: `postgres` con
`POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB`, y `pgvector` con `VECTOR_USER`,
`VECTOR_PASSWORD` y `VECTOR_DB`. En la base de la aplicación, las tablas relevantes son:

- `conversation_messages`: preguntas y respuestas por chat.
- `interview_sessions`: estado y fechas de cada entrevista.
- `interviewer_profiles`: informe y perfil JSON al completar una entrevista.

Detén el entorno con:

```bash
make dev-down
```

## Desplegar producción

Producción corre en una instancia EC2 de AWS y se despliega con `release.yml` y `deploy.yml`, sin
clonar el repositorio en el servidor: las imágenes vienen de Docker Hub y `make prod-up` nunca
construye. Puesta en marcha y operación en [despliegue-aws-ec2.md](despliegue-aws-ec2.md); el flujo
del despliegue y su rollback, en [entornos-y-despliegue.md](entornos-y-despliegue.md#4-el-despliegue-paso-a-paso).

Con los ficheros de la versión ya instalados en `/opt/fitcoachia`, se relanza a mano así (el despliegue
completo, con su rollback, está en
[despliegue-aws-ec2.md](despliegue-aws-ec2.md#83-despliegue-a-mano)):

```bash
cd /opt/fitcoachia
sudo VERSION=1.2.0 make prod-up
```

### Health check del contenedor

El Compose define un `healthcheck` sobre `/health` que Docker sondea **cada 5 minutos** en
régimen estable, para no llenar los logs con una petición cada pocos segundos durante toda la vida
del contenedor. Para que eso no ralentice los despliegues, lleva además `start_interval: 5s`: mientras
el contenedor arranca se sondea cada 5 segundos, así que pasa a `healthy` en cuanto responde y
`make prod-up` (`up --wait`) no espera 5 minutos para darlo por bueno.

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

Para probar rápidamente la generación del informe final en desarrollo, usa `ia_skill=interviewer-dev`
en el `.env` (el valor de `.env.example`). Esta variante solo hace tres preguntas y conserva el
mismo contrato de perfil, persistencia e informe que producción, que usa `ia_skill=interviewer`.
Después de completar una prueba, consulta el informe en pgAdmin o envía `/interview` para empezar
otra.

> **Runtime de contenedores.** El `Makefile` usa `docker` por defecto, que es lo que hay en los
> runners de CI. En local, donde el runtime es podman, pasa la variable en cada invocación:
> `make vector-up DOCKER=podman`, `make dev-up DOCKER=podman`, `make tests DOCKER=podman`.

## Plan de entrenamiento

Con la entrevista completada, `/train` genera un mesociclo de 4 semanas. Requiere dos servicios
adicionales, que `make dev-up` levanta con el resto:

- **pgVector** con el catálogo de ejercicios. La primera vez carga el catálogo al crear su volumen y
  tarda varios minutos. Se puede manejar solo:

  ```bash
  make vector-up      # solo pgvector
  make vector-logs
  make vector-down    # conserva el volumen con la carga inicial
  ```

- **`embedder`**, que vectoriza la consulta con el mismo modelo que el corpus. Lo construye el
  propio `make dev-up`. La primera build descarga el modelo y tarda varios minutos; las siguientes
  usan caché.

Ver [vector-db.md](vector-db.md) para el esquema, el modelo de embeddings y el rol de solo lectura,
y [trainer-agent.md](trainer-agent.md) para el comportamiento del agente.

En desarrollo conviene `ia_trainer_skill=trainer-dev` en el `.env`: desarrolla bien la semana 1 y
deriva las otras tres, con un máximo de 3 ejercicios por día. Mantiene intactas las comprobaciones
que importan (ids del catálogo, 4 semanas, días comprometidos), así que sirve para probar el flujo
completo sin gastar 4096 tokens por iteración.

Repetir `/train` **no** sobrescribe el plan: crea la versión N+1 en `training_plans`. Mientras haya
un plan activo, los mensajes sin comando los responde el entrenador sobre ese plan.
Cada consulta recupera de PostgreSQL el plan más reciente, el perfil disponible y el historial del
entrenador, sin consultar pgVector ni el embedder. Es un modo de solo lectura: explica el plan, pero
no sustituye ejercicios ni guarda ajustes.

### Variables de entorno del entrenador

Plantilla completa en `.env.example`; las propias del entrenador y sus dependencias:

```dotenv
# Agente 2 (entrenador). El mesociclo completo no cabe en ia_max_tokens.
ia_trainer_skill=trainer
ia_trainer_max_tokens=4096
ia_trainer_history_window_messages=10
# Ejercicios recuperados de la BD vectorial por grupo muscular.
ia_rag_top_k=8

# Base de datos vectorial (catalogo de ejercicios). Solo lectura: ver
# infra/vector-db/ddl/002_2026-09-21_readonly-role.sql.
vector_database_url=postgresql+asyncpg://fitcoach_ro:...@pgvector:5432/fitcoach
VECTOR_USER=fitcoach
VECTOR_PASSWORD=...
VECTOR_HOST=pgvector
VECTOR_DB=fitcoach
VECTOR_PORT=5433
VECTOR_DB_RO_PASSWORD=...

# Servicio de embeddings (infra/embedder). DEBE usar el mismo modelo que el
# corpus: all-MiniLM-L6-v2, 384 dimensiones.
embedder_url=http://embedder:8100
embedder_timeout_seconds=10
```

La aplicación no arranca si falta `vector_database_url` o `embedder_url`.

### Avisos y encuestas semanales

Los avisos y las encuestas los ejecuta el scheduler de la app y están desactivados por defecto. Para
probarlos en dev, añadir al `.env` del entorno (plantilla completa en `.env.example`):

```dotenv
scheduler_enabled=true
# Ticks cada 10 s para no esperar en pruebas manuales (mínimo 10).
scheduler_interval_seconds=10
```

Las encuestas vencen a los 7/14/21/28 días del inicio del ciclo; para probarlas sin esperar,
mover hacia atrás `training_mesocycles.started_at` y adelantar `job_execution.execution_date` de los jobs
`evaluation_poll` pendientes del ciclo en la base de dev. Detalle en [scheduler.md](scheduler.md),
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
