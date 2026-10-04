# FitCoach IA - Entrenador Personal Inteligente (TFM)

## 📝 Descripción del Proyecto
**FitCoach IA** es una solución integral de salud y bienestar desarrollada como Trabajo de Fin de Máster (TFM) dentro del **Proyecto Júpiter** . La plataforma utiliza un ecosistema de **IA Generativa** para democratizar el acceso a planes de entrenamiento y nutrición altamente personalizados, basándose en el análisis de datos individuales y hábitos del usuario.

El sistema es capaz de transformar una entrevista inicial en un **Plan Personalizado de 4 semanas** (mesociclo) que abarca entrenamiento, alimentación, suplementación y motivación.

## Arquitectura Multi-Agente (IA Generativa)
El núcleo de FitCoach IA se basa en LLMs con prompts específicos para orquestar cuatro agentes especializados:

*   **Agente 1 (Secretario):** Transcribe entrevistas y genera informes estructurados del cliente.
*   **Agente 2 (Entrenador):** Diseña mesociclos anclados al catálogo RAG, revisa resultados para proponer el siguiente bloque y ofrece sustituciones confirmables de ejercicios. `/train` inicia el primer plan o revisa el vigente; las renovaciones requieren aceptar un borrador. Ver [docs/trainer-agent.md](docs/trainer-agent.md).
*   **Agente 3 (Nutricionista):** Elabora planes de alimentación y suplementación a medida.
*   **Agente 4 (Coaching):** Proporciona soporte motivacional y recursos multimedia personalizados (bibliografía, vídeos, RRSS).

## Stack Tecnológico y Requisitos Técnicos
Este proyecto cumple con los estándares de desarrollo profesional exigidos en el máster:

### Inteligencia Artificial y Datos
- **LLMs:** Uso de APIs de modelos fundacionales (OpenAI/Anthropic) o modelos open-source locales.
- **Bases de Datos Vectoriales:** Implementación obligatoria para la recuperación de recomendaciones semánticas y gestión de conocimientos.
- **Machine Learning:** Redes neuronales para optimización de rutinas basadas en datos históricos de usuarios.

### DevOps e Infraestructura
- **Contenerización:** Todos los agentes y servicios están **dockerizados** para garantizar la portabilidad.
- **CI/CD:** Pipelines automatizados para pruebas unitarias/integradas y despliegue continuo.
- **Cloud:** Despliegue en la nube utilizando **AWS (EC2 y S3)**.
- **Monitorización:** Sistema de logging integrado para trazabilidad de datos y rendimiento del sistema.

### Interfaces de Usuario
- **Web Panel:** Interfaz visual para que el usuario consulte sus datos, rutinas y nutrición.
- **Chatbot (Telegram):** Canal de comunicación directo para actualizar progresos e interactuar con el entrenador en tiempo real.

## Estructura del Proyecto

```
FitCoachIA/
├── src/
│   ├── fitcoach/
│   │   ├── api/                  # Controladores y endpoints REST (webhook de Telegram)
│   │   ├── domain/               # Entidades, enums, errores y textos de usuario
│   │   ├── infrastructure/
│   │   │   ├── bot/              # Cliente de Telegram
│   │   │   ├── config/           # Configuración (settings) y logging
│   │   │   ├── database/         # PostgreSQL conversacional (modelos, sesión, repositorio)
│   │   │   ├── ia/               # Cliente de embeddings y skills de los agentes
│   │   │   ├── jobs/             # Workers: avisos de entrenamiento y encuestas semanales
│   │   │   ├── observability/    # Telemetría OpenTelemetry
│   │   │   ├── prompts/          # Plantillas de prompts por agente
│   │   │   └── vectordb/         # Acceso de solo lectura a pgVector (ejercicios)
│   │   ├── repository/           # Puertos de acceso a datos (Protocol)
│   │   ├── service/              # Casos de uso; agent/ contiene las chains de los agentes
│   │   └── main.py               # Punto de entrada de la aplicación
│   ├── Dockerfile                # Dockerización de la aplicación
│   └── requirements.txt          # Dependencias de runtime (generado desde pyproject.toml)
├── alembic/                      # Migraciones de la base de datos conversacional
├── infra/
│   ├── embedder/                 # Servicio de embeddings (all-MiniLM-L6-v2, 384 dim)
│   ├── observability/            # Grafana, Loki, Tempo, Prometheus, OTel Collector
│   └── vector-db/                # pgVector: DDL del catálogo de ejercicios y cargador
├── tests/
│   ├── unit_test/                # Tests unitarios
│   ├── it/                       # Tests de integración
│   ├── fixtures/                 # Corpus mínimo de pgVector y stub de Telegram/LLM/embedder
│   └── docker-compose-test.yml   # Entorno de los tests de integración
├── docs/                         # Documentación técnica (en español)
├── .github/
│   ├── actions/
│   │   ├── python-setup/         # Action reutilizable: Python + uv + auditoría de dependencias
│   │   └── quality-check/        # Action reutilizable: ruff, mypy, gitleaks, pip-audit, bandit
│   ├── workflows/                # build, release, deploy y validate-develop/main-merge
│   ├── copilot-instructions.md   # Puntero a AGENTS.md
│   └── requirements-ci.txt       # Dependencias del entorno CI (generado desde pyproject.toml)
├── .env.example                  # Plantilla de variables de entorno
├── .dockerignore                 # Contexto de build de la imagen (lista de permitidos)
├── .pre-commit-config.yaml       # Hooks de pre-commit (ruff, gitleaks, bandit)
├── alembic.ini                   # Configuración de alembic
├── docker-compose.dev.yml        # Entorno de desarrollo
├── docker-compose.local.yml      # Entorno local para probar cambios
├── docker-compose.yml            # Entorno de producción
├── pyproject.toml                # Dependencias (fuente de verdad) + config de ruff, mypy y pytest
├── AGENTS.md                     # Mapa del proyecto e instrucciones para asistentes de IA
├── CLAUDE.md                     # Importa AGENTS.md
├── LICENSE.md
├── Makefile                      # Automatización de tareas
└── README.md
```

### Comandos disponibles con Makefile

Ejecuta `make help` para ver todos los comandos disponibles.

| Comando | Descripción |
|---------|-------------|
| `make build [version=x.y.z]` | Construye la imagen Docker (por defecto `latest`; si se indica versión, etiqueta ambas) |
| `make run [version=x.y.z]` | Inicia el contenedor en segundo plano en el puerto 8000 |
| `make stop` | Detiene y elimina el contenedor en ejecución |
| `make logs` | Muestra los logs en tiempo real del contenedor |
| `make clean` | Detiene el contenedor y elimina todas las imágenes locales de la aplicación |
| `make all` | Secuencia completa: limpia, construye y arranca |
| `make container` | Lista todos los contenedores (activos y detenidos) |
| `make clean-image [version=x.y.z]` | Elimina solo la imagen de la versión indicada (por defecto `latest`) |
| `make clean-images` | Elimina todas las imágenes locales de la aplicación |
| `make tests` | Levanta el entorno de tests, ejecuta unitarios e integración con cobertura (falla si < 80%) y lo detiene |
| `make dev-up` / `dev-down` / `dev-logs` | Entorno de desarrollo (`docker-compose.dev.yml`) |
| `make prod-up [VERSION=x.y.z]` / `prod-down` / `prod-logs` | Entorno de producción (`docker-compose.yml`) |
| `make vector-up` / `vector-down` / `vector-logs` | Base de datos vectorial (`infra/vector-db`) |

El detalle de cada comando y de sus variables está en [docs/Makefile.md](docs/Makefile.md).


## Instalación y Despliegue
Instrucciones para poner en marcha el sistema utilizando los scripts de despliegue incluidos:

```bash
# Clonar el repositorio
git clone https://github.com/usuario/proyecto-jupiter.git

## 🐳 Docker — Construcción manual de la imagen

El `Dockerfile` se encuentra en `src/`, pero el contexto de construcción es la **raíz del repositorio**: copia `src/requirements.txt`, `src/fitcoach`, `alembic` y `alembic.ini`. El `.dockerignore` es una lista de permitidos, de modo que solo esos ficheros entran en el contexto.

### 1. Construir la imagen

```bash
# Desde la raíz del repositorio
docker build -t fitcoach-ia:latest -f src/Dockerfile .
```

> **Nota:** La etiqueta `fitcoach-ia:latest` puede sustituirse por cualquier nombre y versión que prefieras (p. ej. `fitcoach-ia:1.0.0`). `make build` hace lo mismo con la imagen `fitcoachia/fitcoach-app`.

### 2. Ejecutar el contenedor

La aplicación expone el **puerto 8000**. Para lanzarla pasando las variables de entorno necesarias:

```bash
docker run -d -p 8000:8000 fitcoach-ia:latest
```
En el supuesto de necesitar variables de entorno, los comandos a utilizar podrían ser:

````bash
# Usando un fichero con variables de entorno
docker run -d -p 8000:8000 --env-file=<path_to_file> fitcoach-ia:latest

# Añadiendo las variables de entorno a mano
docker run -d -p 8000:8000 --e <ENVVAR_NAME>=<ENVVAR_VALUE> fitcoach-ia:latest

`````

Una vez en marcha, la API estará disponible en `http://localhost:8000`.

### 3. Referencia rápida de opciones de `docker build`

| Opción | Descripción |
|--------|-------------|
| `-t fitcoach-ia:latest` | Nombre y etiqueta de la imagen resultante |
| `-f src/Dockerfile` | Ruta del `Dockerfile` |
| `.` | Contexto de construcción (raíz del repositorio) |
| `--no-cache` | Fuerza la reconstrucción de todas las capas sin caché |
| `--platform linux/amd64` | Construye para una plataforma específica (útil en Apple Silicon) |

## CI/CD

El proyecto tiene estos workflows en `.github/workflows/`:

| Workflow | Trigger | Qué hace |
|----------|---------|----------|
| `build.yml` | Push y PRs en ramas `feat/**`, `feature/**`, `fix/**`, `bugfix/**` (ignora cambios solo de docs y `.md`) y ejecución manual | Calidad y seguridad (Ruff, Mypy, Gitleaks, pip-audit, Bandit, Semgrep) → `make tests` (unitarios e integración, cobertura >= 80%) |
| `validate-develop-merge.yml` | PRs a `develop` | Bloquea merges que no provengan de ramas `feat/`, `feature/` o `fix/` |
| `validate-main-merge.yml` | PRs a `main` | Bloquea merges que no provengan de `develop` |
| `release.yml` | Ejecución manual con versión `X.Y.Z` desde `develop` o `release/**` | Construye la imagen Docker, la escanea con Trivy, publica en el registry, crea la GitHub Release y lanza `deploy.yml` |
| `deploy.yml` | Llamado por `release.yml` o manual | Despliega la versión en el servidor por SSH con `make prod-up`, verifica el arranque y hace rollback si falla |

Las actions reutilizables están en `.github/actions/`: `python-setup` instala Python y `uv` con caché y audita `requirements-ci.txt` antes de instalar; `quality-check` agrupa Ruff, Mypy, Gitleaks, pip-audit y Bandit. El detalle está en [docs/ci-cd.md](docs/ci-cd.md).

## Tests

Los imports de la aplicación se resuelven solos: `pythonpath = ["src"]` en `pyproject.toml` ya apunta a `src/`, sin necesidad de exportar `PYTHONPATH` a mano.

Los tests de integración (`tests/it`) atacan por HTTP el contenedor construido desde `src/Dockerfile`, así que requieren Docker en marcha. `make tests` lo levanta y lo detiene automáticamente.

```bash
# Todos los tests: unitarios con cobertura (falla si < 80%) + integración contra el contenedor
make tests
```

La configuración por defecto de pytest (paths, formato de logs, verbosidad) vive en `pyproject.toml` bajo `[tool.pytest.ini_options]`.

## Pre-commit

El proyecto usa [pre-commit](https://pre-commit.com/) para ejecutar validaciones automáticas en cada `git commit` local, antes de que el código llegue al pipeline de CI. El objetivo es detectar problemas triviales (formato, secretos expuestos, errores de lint) en el momento más barato posible: el propio equipo de desarrollo.

### Por qué pre-commit

- **Feedback inmediato**: los errores se detectan en el commit, no en la PR ni en CI.
- **Consistencia**: todos los contribuidores aplican las mismas reglas sin depender de configuraciones de editor.
- **Complementa CI**: CI actúa como red de seguridad; pre-commit evita que lleguen errores evitables.

### Hooks configurados

| Hook | Propósito |
|------|-----------|
| `trailing-whitespace`, `end-of-file-fixer` | Higiene básica de ficheros |
| `check-yaml` | Valida sintaxis de ficheros YAML |
| `check-merge-conflict` | Bloquea commits con marcadores de conflicto (`<<<<<<`) |
| `check-added-large-files` (máx. 500 KB) | Evita subir binarios pesados al repositorio |
| `no-commit-to-branch` (`main`, `develop`) | Impide commits directos a ramas protegidas |
| `gitleaks` | Escanea el diff en busca de credenciales o tokens expuestos |
| `ruff` + `ruff-format` | Linter y formateador Python (equivalente a Flake8 + Black) |
| `bandit` | Análisis estático de seguridad (SAST) sobre el código de aplicación |

### Configuración en local (una sola vez por clon)

```bash
# 1. Instalar pre-commit (si no está ya en el entorno)
pip install pre-commit
# o con uv:
uv pip install pre-commit

# 2. Registrar los hooks en el repositorio local
pre-commit install

# 3. (Recomendado) Ejecutar contra todos los ficheros para partir de un estado limpio
pre-commit run --all-files
```

A partir de ese momento los hooks se ejecutan automáticamente en cada `git commit`.

### Comandos útiles

```bash
# Actualizar las versiones (rev) de los hooks al último release
pre-commit autoupdate

# Saltar un hook concreto manteniendo el resto activo
SKIP=gitleaks git commit -m "mensaje"
SKIP=ruff,bandit git commit -m "mensaje"   # varios separados por coma

# Saltar todos los hooks para un commit puntual (úsese con criterio)
git commit --no-verify

# Desinstalar los hooks del repositorio local
pre-commit uninstall
```

## Licencia y Cita

Este proyecto está bajo la licencia **Creative Commons Atribución-NoComercial 4.0 Internacional (CC BY-NC 4.0)**.

Si utilizas este trabajo en una investigación académica o proyecto, por favor cítalo como:
> [Apellidos, N. de los autores]. (Año). [Título del TFM]. Repositorio de GitHub. [Enlace al repo].
