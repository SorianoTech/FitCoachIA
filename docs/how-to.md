# Levantar el entorno de desarrollo

## Requisitos

- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Docker y Docker Compose, para PostgreSQL
- Un bot de Telegram y un endpoint compatible con OpenAI para probar el flujo completo

## Entornos y variables

| Entorno | Compose | Proyecto | API | Base de datos |
|---|---|---|---|---|
| Desarrollo | `docker-compose.dev.yml` | `fitcoach-dev` | `dev-fitcoach-ia`, `proxy-network` | volumen `fitcoach-dev-postgres` |
| Producción | `docker-compose.yml` | `fitcoach-prod` | `fitcoach-ia`, `proxy-network` | volumen `fitcoach-prod-postgres` |

`APP_ENV` se establece automáticamente como `dev` o `prod` en cada Compose. La aplicación carga
`.env.<APP_ENV>` si existe y después `.env`; las variables del sistema tienen prioridad.

Los `make dev-up` / `make prod-up` (ver más abajo) leen el fichero de entorno de fuera del
repositorio, en `/etc/fitcoachia/<entorno>/`:

| Entorno | Fichero preferido | Si no existe |
|---|---|---|
| Desarrollo | `/etc/fitcoachia/dev/.env.dev` | usa `.env.dev` en la raíz del repositorio |
| Producción | `/etc/fitcoachia/prod/.env.prod` | falla: no hay fallback en producción |

Crea el fichero correspondiente a cada entorno:

```bash
# Desarrollo (opcional, si no existe se usa .env.dev del repositorio)
sudo mkdir -p /etc/fitcoachia/dev
sudo cp .env.example /etc/fitcoachia/dev/.env.dev

# Producción (obligatorio)
sudo mkdir -p /etc/fitcoachia/prod
sudo cp .env.example /etc/fitcoachia/prod/.env.prod
```

En local, si prefieres no usar `/etc/fitcoachia`, basta con crear `.env.dev` en la raíz del
repositorio:

```bash
cp .env.example .env.dev
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
interna contra el servicio `postgres-dev`/`postgres-prod` (nombre distinto por entorno para evitar que
ambos reclamen el mismo alias de red en `proxy-network`), por lo que cada entorno conserva el
historial del agente `interviewer` en una base de datos independiente.

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

### Consultar la base de datos con Adminer

El entorno de desarrollo incluye Adminer, una interfaz web para consultar los mensajes, sesiones y
perfiles del entrevistador. No publica ningún puerto en el host: crea un Proxy Host en Nginx Proxy
Manager que apunte a `dev-fitcoach-adminer`, puerto `8080` y protocolo `http`.

Protege ese Proxy Host antes de publicarlo mediante una *Access List* de Nginx Proxy Manager y, si
es posible, una restricción por IP. No añadas Adminer a `docker-compose.yml` de producción.

En la pantalla de inicio de sesión de Adminer selecciona PostgreSQL. El campo del servidor ya estará
rellenado con `postgres-dev`; usa los valores `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` de
`.env.dev`. Tras iniciar sesión, las tablas relevantes son:

- `conversation_messages`: preguntas y respuestas por chat.
- `interview_sessions`: estado y fechas de cada entrevista.
- `interviewer_profiles`: informe y perfil JSON al completar una entrevista.

Detén el entorno con:

```bash
make dev-down
```

## Desplegar producción

Producción utiliza `docker-compose.yml`, el proyecto `fitcoach-prod`, la red externa
`proxy-network`. Nginx Proxy Manager publica la API; antes del primer despliegue, crea esa red y
el fichero `/etc/fitcoachia/prod/.env.prod` exclusivo del servidor de producción (ver
[Entornos y variables](#entornos-y-variables)). `make prod-up` falla si ese fichero no existe o no
tiene permisos de acceso.

`/etc/fitcoachia/prod` mantiene permisos restringidos: el usuario de despliegue (SSH) no puede
leerlo directamente. El workflow `deploy.yml` accede solo durante el comando de despliegue
mediante `sudo -n`, así que ese usuario necesita una regla `sudoers` sin contraseña:

```
# /etc/sudoers.d/fitcoach-deploy   (chmod 0440, validar con visudo -c)
<SERVER_USER> ALL=(root) NOPASSWD: /usr/bin/make, /usr/bin/test, /bin/ls
```

```bash
docker network inspect proxy-network >/dev/null 2>&1 || docker network create proxy-network
make prod-up VERSION=0.3.0
```

Para desplegar manualmente en el servidor con ese usuario restringido, antepón `sudo`:

```bash
sudo make prod-up VERSION=0.3.0
```

Desarrollo y producción pueden convivir en el mismo servidor. Usa `make dev-up` para el entorno
de desarrollo y `make prod-up VERSION=<version>` para producción; cada uno mantiene sus propios
contenedores, volumen PostgreSQL y configuración `APP_ENV`.

## Pruebas y comprobaciones

## Entrevistas y perfil

El agente `interviewer` guarda el historial por chat mientras la entrevista está en progreso. Al
completar las preguntas, valida y guarda el perfil estructurado en PostgreSQL y envía un informe de
resumen por Telegram. Los mensajes posteriores indican que el perfil está completado; envía
`/interview` para reemplazar el perfil actual e iniciar una entrevista limpia.

Para probar rápidamente la generación del informe final en desarrollo, `make dev-up` configura
automáticamente la skill `interviewer-dev`. Esta variante solo hace tres preguntas y conserva el
mismo contrato de perfil, persistencia e informe que producción. La skill completa se mantiene
activa en producción con `ia_skill=interviewer`. Después de completar una prueba, consulta el
informe en Adminer o envía `/interview` para empezar otra.

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
