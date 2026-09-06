# Levantar el entorno de desarrollo

## Requisitos

- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Docker y Docker Compose, para PostgreSQL
- Un bot de Telegram y un endpoint compatible con OpenAI para probar el flujo completo

## Configurar variables

Desde la raíz del repositorio, crea el fichero local de configuración:

```bash
cp .env.example .env
```

Completa al menos estas variables en `.env`:

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

`database_url` se utiliza cuando la API se ejecuta con Python local. El historial del agente
`interviewer` se guarda por chat de Telegram en esta base de datos.

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

## Ejecutar todo con Docker Compose

Esta opción ejecuta PostgreSQL y la API en contenedores. El contenedor de la API aplica
automáticamente `alembic upgrade head` antes de iniciar FastAPI.

```bash
docker network inspect proxy-network >/dev/null 2>&1 || docker network create proxy-network
make build
docker compose up -d
```

Consulta los logs de la API:

```bash
docker compose logs -f fitcoach-ia
```

Detén el entorno con:

```bash
docker compose down
```

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