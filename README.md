# FitCoach IA - Entrenador Personal Inteligente (TFM)

## 📝 Descripción del Proyecto
**FitCoach IA** es una solución integral de salud y bienestar desarrollada como Trabajo de Fin de Máster (TFM) dentro del **Proyecto Júpiter** . La plataforma utiliza un ecosistema de **IA Generativa** para democratizar el acceso a planes de entrenamiento y nutrición altamente personalizados, basándose en el análisis de datos individuales y hábitos del usuario.

El sistema es capaz de transformar una entrevista inicial en un **Plan Personalizado de 4 semanas** (mesociclo) que abarca entrenamiento, alimentación, suplementación y motivación.

## Arquitectura Multi-Agente (IA Generativa)
El núcleo de FitCoach IA se basa en LLMs con prompts específicos para orquestar cuatro agentes especializados:

*   **Agente 1 (Secretario):** Transcribe entrevistas y genera informes estructurados del cliente.
*   **Agente 2 (Entrenador):** Diseña planes de entrenamiento optimizados en mesociclos.
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
│   │   ├── api/                  # Controladores y endpoints REST
│   │   ├── domain/               # Entidades y lógica de dominio
│   │   ├── infrastructure/
│   │   │   ├── config/           # Configuración de la aplicación
│   │   │   ├── database/         # Conexión y setup de base de datos
│   │   │   ├── ia/               # Clientes y adaptadores de LLMs
│   │   │   └── prompts/          # Plantillas de prompts por agente
│   │   ├── repository/           # Acceso a datos (patrón Repository)
│   │   ├── service/              # Casos de uso y lógica de negocio
│   │   └── main.py               # Punto de entrada de la aplicación
│   ├── Dockerfile                # Dockerización de la aplicación
│   └── requirements.txt          # Dependencias del contenedor
├── tests/
│   ├── unit_test/                     # Tests unitarios
│   └── it/                       # Tests de integración
├── docs/                         # Documentación técnica
│   ├── AUTHORS.md
│   ├── Dockerfile-guide.md
│   └── Makefile.md
├── .github/
│   ├── actions/
│   │   └── python-setup.yml      # Action reutilizable: instala Python + uv + audita dependencias
│   ├── workflows/
│   │   ├── build.yml             # Pipeline de calidad, seguridad y tests (feature branches)
│   │   ├── release.yml           # Publicación de imagen Docker y release en GitHub (main)
│   │   └── validate-merge-source.yml  # Valida que los PRs a main vengan de develop
│   └── requirements-ci.txt       # Dependencias del entorno CI (herramientas + src/requirements.txt)
├── scripts/                      # Scripts de utilidad
├── .env.development              # Variables de entorno para desarrollo
├── .env.example                  # Plantilla de variables de entorno
├── .pre-commit-config.yaml       # Hooks de pre-commit (ruff, gitleaks, bandit)
├── docker-compose.yml            # Configuración de Docker Compose
├── pyproject.toml                # Configuración de ruff, mypy y pytest
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
| `make images` | Lista todas las imágenes Docker locales |
| `make clean-images` | Elimina todas las imágenes locales de la aplicación |
| `make tag version=x.y.z` | Aplica un tag de versión a la imagen `latest` local |
| `make tests` | Todos los tests con cobertura (falla si < 80%) |
| `make unit_tests` | Solo tests unitarios (sin cobertura) |
| `make it_tests` | Solo tests de integración (sin cobertura) |


## Instalación y Despliegue
Instrucciones para poner en marcha el sistema utilizando los scripts de despliegue incluidos:

```bash
# Clonar el repositorio
git clone https://github.com/usuario/proyecto-jupiter.git

## 🐳 Docker — Construcción manual de la imagen

El `Dockerfile` se encuentra en `src/` y requiere que el contexto de construcción sea ese mismo directorio, ya que copia la carpeta `fitcoach/` y el fichero `requirements.txt` desde allí.

### 1. Construir la imagen

```bash
# Desde la raíz del repositorio
docker build -t fitcoach-ia:latest ./src
```

> **Nota:** La etiqueta `fitcoach-ia:latest` puede sustituirse por cualquier nombre y versión que prefieras (p. ej. `fitcoach-ia:1.0.0`).

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
| `./src` | Contexto de construcción (directorio donde está el `Dockerfile`) |
| `--no-cache` | Fuerza la reconstrucción de todas las capas sin caché |
| `--platform linux/amd64` | Construye para una plataforma específica (útil en Apple Silicon) |

## CI/CD

El proyecto tiene tres pipelines en `.github/workflows/`:

| Workflow | Trigger | Qué hace |
|----------|---------|----------|
| `build.yml` | PRs a ramas `feature/**`, `fix/**` | Calidad y seguridad (Ruff, Mypy, Gitleaks, pip-audit, Bandit, Semgrep) → tests unitarios y de integración (cobertura >= 80%)|
| `validate-merge-source.yml` | PRs a `main` | Bloquea merges que no provengan de `develop` |
| `release.yml` | Push a `main` | Construye la imagen Docker, escanea vulnerabilidades con Trivy, publica en el registry, crea la GitHub Release con versionado semver automático y despliega al servidor |

La action `.github/actions/python-setup.yml` es reutilizable entre los workflows: instala la versión de Python configurada, instala `uv` con caché de dependencias y audita `requirements-ci.txt` antes de instalar.

## Tests

El proyecto requiere que `PYTHONPATH` apunte a `src/` para que los imports de la aplicación se resuelvan correctamente.

```bash
# Todos los tests con análisis de cobertura (falla si cobertura < 80%)
PYTHONPATH=src pytest tests --cov=src/fitcoach --cov-fail-under=80

# Solo tests unitarios (sin análisis de cobertura)
PYTHONPATH=src pytest tests/unit --no-cov

# Solo tests de integración (sin análisis de cobertura)
PYTHONPATH=src pytest tests/it --no-cov
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

# Saltar los hooks puntualmente (úsese con criterio)
git commit --no-verify

# Desinstalar los hooks del repositorio local
pre-commit uninstall
```

## Licencia y Cita

Este proyecto está bajo la licencia **Creative Commons Atribución-NoComercial 4.0 Internacional (CC BY-NC 4.0)**.

Si utilizas este trabajo en una investigación académica o proyecto, por favor cítalo como:
> [Apellidos, N. de los autores]. (Año). [Título del TFM]. Repositorio de GitHub. [Enlace al repo].
