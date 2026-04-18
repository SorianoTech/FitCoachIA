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
│   │   │   │   └── skills/       # Skills y datos RAG por agente
│   │   │   │       ├── coach/
│   │   │   │       ├── interviewer/
│   │   │   │       ├── nutrionist/
│   │   │   │       └── trainer/
│   │   │   └── prompts/          # Plantillas de prompts por agente
│   │   ├── repository/           # Acceso a datos (patrón Repository)
│   │   ├── service/              # Casos de uso y lógica de negocio
│   │   └── main.py               # Punto de entrada de la aplicación
│   ├── Dockerfile                # Dockerización de la aplicación
│   └── requirements.txt          # Dependencias del contenedor
├── tests/
│   ├── unit/                     # Tests unitarios
│   └── integration/              # Tests de integración
├── .github/
│   └── workflows/                # Pipelines CI/CD
├── docker/                       # Configuración de contenedores
├── scripts/                      # Scripts de utilidad
├── .env.development              # Variables de entorno para desarrollo
├── .env.example                  # Plantilla de variables de entorno
├── .env.test                     # Variables de entorno para tests
├── AUTHORS.md
├── LICENSE.md
├── Makefile                      # Automatización de tareas
├── README.md
├── comandos.md                   # Resumen de comandos útiles
└── requirements.txt              # Dependencias Python (entorno local)
```


## Instalación y Despliegue
Instrucciones para poner en marcha el sistema utilizando los scripts de despliegue incluidos:

```bash
# Clonar el repositorio
git clone https://github.com/usuario/proyecto-jupiter.git

# Ejecutar despliegue con Docker
cd docker
bash deploy.sh
```

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

## Pruebas
Para ejecutar las pruebas unitarias e integradas:

```
pytest tests/
```

## Licencia y Cita

Este proyecto está bajo la licencia **Creative Commons Atribución-NoComercial 4.0 Internacional (CC BY-NC 4.0)**. 

Si utilizas este trabajo en una investigación académica o proyecto, por favor cítalo como:
> [Apellidos, N. de los autores]. (Año). [Título del TFM]. Repositorio de GitHub. [Enlace al repo].
