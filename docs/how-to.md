# Levantar el entorno de desarrollo

## Requisitos

- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Docker y Docker Compose, para PostgreSQL
- Un bot de Telegram y un endpoint compatible con OpenAI para probar el flujo completo

## Entornos y variables

| Entorno | Compose | Proyecto | API | Base de datos |
|---|---|---|---|---|
| Desarrollo | `docker-compose.dev.yml` | `fitcoach-dev` | `dev-fitcoach-ia`, puerto 8001 y `proxy-network` | volumen `fitcoach-dev-postgres` |
| Producción | `docker-compose.yml` | `fitcoach-prod` | `fitcoach-ia`, puerto 8000 y `proxy-network` | volumen `fitcoach-prod-postgres` |

`APP_ENV` se establece automáticamente como `dev` o `prod` en cada Compose. La aplicación carga
`.env.<APP_ENV>` si existe y después `.env`; las variables del sistema tienen prioridad.

En el mismo servidor, crea un fichero por entorno desde la raíz del repositorio:

```bash
cp .env.example .env.dev
cp .env.example .env.prod
```

Completa al menos estas variables en cada fichero. Usa el bot y endpoint de desarrollo en
`.env.dev`, y las credenciales de producción en `.env.prod`:

```dotenv
bot_telegram_url=...
bot_telegram_token=...
bot_telegram_commands=start:Inicia FitCoach,interview:Entrevista,doubts:Resuelve dudas,progress:Tu progreso

ia_base_url=...
ia_token=...
ia_model=...
ia_temperature=0.5
ia_history_window_messages=20

POSTGRES_USER=fitcoach
POSTGRES_PASSWORD=elige-una-contrasena
POSTGRES_DB=fitcoach
database_url=postgresql+asyncpg://fitcoach:elige-una-contrasena@localhost:5432/fitcoach
```

`database_url` se utiliza cuando la API se ejecuta con Python local. Los Compose crean su propia URL
interna contra el servicio `postgres`, por lo que cada entorno conserva el historial del agente
`interviewer` en una base de datos independiente.

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

## Ejecutar desarrollo con Docker Compose

Esta opción ejecuta PostgreSQL y la API en contenedores. El contenedor de la API aplica
automáticamente `alembic upgrade head` antes de iniciar FastAPI.

```bash
docker network inspect proxy-network >/dev/null 2>&1 || docker network create proxy-network
make dev-up
```

Consulta los logs de la API:

```bash
make dev-logs
```

Detén el entorno con:

```bash
make dev-down
```

## Desplegar producción

Producción utiliza `docker-compose.yml`, el proyecto `fitcoach-prod`, la red externa
`proxy-network` y publica la API en el puerto 8000. Antes del primer despliegue, crea esa red y
configura un `.env` exclusivo en el servidor de producción.

```bash
docker network inspect proxy-network >/dev/null 2>&1 || docker network create proxy-network
make prod-up version=0.3.0
```

Desarrollo y producción pueden convivir en el mismo servidor. Usa `make dev-up` para el entorno
de desarrollo y `make prod-up version=<version>` para producción; cada uno mantiene sus propios
contenedores, volumen PostgreSQL y configuración `APP_ENV`.

## Pruebas y comprobaciones

```bash
# Suite completa con cobertura mínima del 80 %
uv run pytest tests --cov=src/fitcoach --cov-fail-under=80

# Solo unitarias o integración
uv run pytest tests/unit_test --no-cov
uv run pytest tests/it --no-cov

# Calidad y tipos
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```