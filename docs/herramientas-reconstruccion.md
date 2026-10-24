# Herramientas para reconstruir FitCoachIA desde cero

Este documento propone el equipo técnico que usaría para volver a desarrollar FitCoachIA,
partiendo de su arquitectura actual: un monolito modular en FastAPI, integración con Telegram,
agentes LLM, RAG de ejercicios, PostgreSQL y despliegue en contenedores. Es una guía de selección,
no una lista de instalaciones ni una decisión de adoptar todos los servicios.

## Criterio general

Mantendría primero un producto pequeño y verificable: entrevista, generación de un plan basado en
el catálogo de ejercicios, persistencia y conversación por Telegram. Añadiría infraestructura,
agentes y automatizaciones a medida que los requisitos lo justifiquen. No empezaría con
microservicios ni con varios agentes independientes: el diseño actual de monolito modular permite
separar responsabilidades sin pagar ese coste operativo.

La base actual y el contexto del proyecto están descritos en [AGENTS.md](../AGENTS.md); el setup,
en [how-to.md](how-to.md); y la propuesta cloud, en [arquitectura-aws.md](arquitectura-aws.md).

## Herramientas de desarrollo

| Herramienta | Prioridad | Para qué la usaría |
|---|---|---|
| Git y GitHub | Imprescindible | Historial revisable, ramas, PR, protección de ramas y colaboración. |
| VS Code | Recomendada | Entorno de edición, depuración y acceso a pruebas, Git y terminal. No es requisito del runtime. |
| Python y `uv` | Imprescindible | Python para la aplicación y `uv` para resolver, sincronizar y fijar dependencias desde `pyproject.toml`. El proyecto declara Python 3.12 o superior. |
| Make | Recomendada | Una interfaz estable para tareas locales, contenedores, pruebas y utilidades del proyecto. |
| Docker Engine y Docker Compose | Imprescindible para el entorno completo | Reproducir API, PostgreSQL, pgVector, embedder y pruebas de integración sin instalar cada servicio a mano. |

### Extensiones de VS Code

Las extensiones mejoran la experiencia, pero las comprobaciones deben seguir ejecutándose también
por CLI y en CI.

| Extensión | Prioridad | Uso |
|---|---|---|
| Python y Pylance | Recomendada | Intérprete, navegación, autocompletado, análisis y depuración Python. |
| Ruff | Recomendada | Diagnósticos y formato Python alineados con la configuración del repositorio. |
| Docker | Recomendada si se trabaja con contenedores | Inspección de imágenes, contenedores y archivos Compose. |
| GitHub Actions | Recomendada | Validación y navegación de workflows del pipeline. |
| YAML y TOML | Recomendadas | Edición y validación de workflows, Compose y `pyproject.toml`. |
| Cliente PostgreSQL | Opcional | Consultas locales de desarrollo; usar únicamente bases de datos y credenciales de desarrollo. |

No hace falta instalar una extensión por cada framework ni exponer credenciales reales al editor.

## Stack de aplicación y servicios

| Área | Herramientas o servicio | Motivo |
|---|---|---|
| API y validación | FastAPI, Pydantic y `pydantic-settings` | Webhook HTTP, modelos de entrada/salida y configuración validada al arrancar. |
| Bot | Telegram Bot API y `python-telegram-bot` | Canal de conversación y entrega de respuestas, encuestas y avisos. |
| Agentes | LangChain Core y `langchain-openai`, con una API LLM compatible con OpenAI | Componer llamadas a modelos manteniendo la posibilidad de cambiar de proveedor. El proveedor y el coste deben poder configurarse y medirse. |
| Persistencia | PostgreSQL, SQLAlchemy asíncrono, asyncpg y Alembic | Guardar conversaciones, perfiles, planes y datos operativos; versionar cambios de esquema. |
| RAG | PostgreSQL con pgVector y un servicio de embeddings | Recuperar ejercicios pertinentes y limitar los planes a ejercicios del catálogo. El modelo de embeddings debe coincidir con el usado para indexar el corpus. |
| Tareas programadas | Scheduler dentro de la aplicación y PostgreSQL | Recordatorios y encuestas con estado persistente y ejecución recuperable tras reinicios. |
| Configuración | Variables de entorno validadas y ficheros de ejemplo | Separar configuración por entorno sin guardar secretos en el código ni en Git. |

Para reconstruir el MVP empezaría con Interviewer y Trainer, el catálogo de ejercicios y los flujos
de `/interview` y `/train`. Nutrición, coaching, paneles u otros canales se incorporarían solo
cuando sus requisitos, datos y alcance estén definidos.

## Pruebas, calidad y seguridad

| Herramienta | Prioridad | Para qué la usaría |
|---|---|---|
| pytest y pytest-asyncio | Imprescindible | Pruebas unitarias asíncronas, además de las pruebas de integración del webhook y persistencia. |
| Ruff | Imprescindible | Lint y formato consistentes. |
| mypy | Recomendada | Comprobar tipos y contratos, especialmente en los límites entre dominio, puertos y adaptadores. |
| pre-commit | Recomendada | Ejecutar comprobaciones rápidas antes de cada commit. |
| Gitleaks | Imprescindible en CI | Detectar secretos añadidos accidentalmente al repositorio. |
| Bandit y pip-audit | Recomendadas en CI | Revisar patrones inseguros en Python y vulnerabilidades conocidas en dependencias. |
| Semgrep | Recomendada en CI | Análisis estático adicional para patrones de riesgo. |
| Trivy | Recomendada para imágenes | Revisar vulnerabilidades de las imágenes de contenedor antes de publicarlas. |
| Stubs de Telegram, LLM y embeddings | Imprescindibles para pruebas reproducibles | Probar respuestas correctas, errores, timeouts y formatos inválidos sin depender de servicios externos ni consumir tokens. |
| Golden set y evaluador de planes | Imprescindibles para iterar sobre el Trainer | Comparar calidad, errores, tokens y latencia cuando cambian el prompt, la skill, el modelo o la recuperación. |

Las pruebas de lógica deben ser rápidas y aisladas; las de integración deben reproducir los límites
reales con servicios locales y datos de prueba. No usaría cuentas reales ni perfiles reales como
fixtures.

## CI/CD y operación

| Herramienta | Prioridad | Para qué la usaría |
|---|---|---|
| GitHub Actions | Imprescindible si GitHub aloja el repositorio | Ejecutar calidad, seguridad, pruebas, publicación de imágenes y despliegue. |
| Registro de imágenes, por ejemplo Amazon ECR | Necesario al desplegar en AWS | Publicar imágenes versionadas y consumibles por el entorno de ejecución. |
| OpenTelemetry | Recomendada desde el inicio | Instrumentar peticiones y dependencias con trazas y métricas sin acoplar la aplicación a un proveedor. |
| Prometheus, Grafana, Loki y Tempo | Opcionales, adecuados para la pila autoalojada actual | Consultar métricas, dashboards, logs y trazas. Se pueden sustituir por servicios administrados si el coste operativo lo aconseja. |
| AWS y Terraform | Solo si se confirma AWS como destino | Definir infraestructura reproducible. La propuesta existente contempla, entre otros, ECS/Fargate, RDS, ALB, ECR, Secrets Manager, redes privadas y recuperación. Terraform no es necesario para desarrollar o probar localmente. |

El despliegue debe separar desarrollo, pruebas y producción, aplicar migraciones de forma
controlada y obtener los secretos desde un almacén seguro. La alta disponibilidad, recuperación,
región, costes y objetivos RPO/RTO son decisiones de producto/operación que deben validarse, no
valores que se deban copiar automáticamente de un diagrama.

## Skills para el asistente de desarrollo

Una *skill* de desarrollo aporta instrucciones y conocimiento reutilizable al asistente de
programación. No es lo mismo que una skill de runtime: las carpetas
`src/fitcoach/infrastructure/ia/skills/` contienen conocimiento que se entrega a los agentes de
FitCoachIA cuando atienden a usuarios.

### Skills que reutilizaría

| Skill | Aplicación |
|---|---|
| `cloud-architect` | Diseñar y revisar la arquitectura AWS, redes, seguridad, costes y recuperación antes de desplegar. |
| `aws-architecture-diagram` | Crear o mantener diagramas coherentes con los servicios AWS escogidos. |
| `prompt-engineering` | Diseñar prompts estructurados y mejorar instrucciones mediante evaluación, no solo por inspección subjetiva. |

Estas skills ya existen en `.github/skills/`; comprobaría su compatibilidad y vigencia antes de
reutilizarlas en un nuevo entorno de agentes.

### Skills específicas que añadiría cuando aporten valor

1. **Arquitectura FitCoachIA:** límites entre API, servicio, dominio, puertos y adaptadores; composición
   en `main.py`; convenciones de errores, configuración y logging.
2. **Agentes, RAG y evaluación:** restricciones del catálogo, recuperación, validación de salida,
   reparación acotada y comparación con golden sets.
3. **Telegram y flujos conversacionales:** parsing de updates, callbacks, respuestas en hilos y
   comportamiento ante errores para evitar reintentos no deseados.
4. **Persistencia y migraciones:** modelos SQLAlchemy, repositorios, Alembic y compatibilidad de
   cambios de esquema.
5. **Pruebas y seguridad:** dobles de servicios externos, casos OK/KO, manejo de datos sensibles y
   comandos de verificación del proyecto.

No las crearía todas de antemano: empezaría por instrucciones generales concisas y extraería una
skill solo cuando el conocimiento sea recurrente, acotado y útil en varios cambios. Las reglas
centrales del repositorio deben permanecer en `AGENTS.md`, no duplicarse en múltiples skills.

## Plugins, MCP e integraciones del asistente

En este contexto, llamo *plugins* a extensiones del editor y a integraciones MCP; no son
dependencias que necesite la aplicación para arrancar.

| Integración | Prioridad | Uso y límites |
|---|---|---|
| GitHub MCP | Opcional | Consultar issues, PR, ramas y workflows desde el asistente. Usar permisos mínimos y confirmar antes de operaciones que publiquen cambios. |
| Documentación de LangChain | Opcional | Consultar documentación actualizada de las APIs usadas, especialmente cuando se cambien versiones. |
| Herramientas de navegación del repositorio y terminal del IDE | Recomendadas | Buscar código, editar y ejecutar pruebas localmente; revisar el diff antes de aceptar los cambios. |
| MCP de base de datos | No necesario para empezar | Si se incorpora, limitarlo a una base local de prueba, con permisos de solo lectura siempre que sea posible. Nunca conectarlo a producción para automatizar cambios. |

No instalaría un servidor MCP porque sí: las extensiones de VS Code y los comandos locales bastan
para la mayoría de las tareas. Las integraciones externas deben tener un beneficio concreto,
permisos mínimos y no recibir secretos, datos personales ni contenido privado del proyecto.

## Orden recomendado de trabajo

1. Definir alcance del MVP, modelo de datos, límites de privacidad y proveedor LLM.
2. Preparar Python, `uv`, Git, estructura modular, configuración validada y pruebas unitarias.
3. Implementar webhook de Telegram y el flujo de entrevista con persistencia y migraciones.
4. Incorporar catálogo pgVector, embeddings, recuperación y evaluación del plan de entrenamiento.
5. Añadir pruebas de integración, Compose de pruebas, lint, tipos y análisis de seguridad.
6. Configurar CI, observabilidad y despliegue; incorporar AWS/Terraform solo tras decidir el destino.
7. Ampliar agentes y canales tras validar calidad, coste y necesidades de usuarios.

## Decisiones que conviene confirmar al reiniciar

- Alinear la versión de Python en runtime, contenedores y herramientas: la configuración del proyecto
  declara Python 3.12 o superior, mientras que parte de la configuración de análisis estático usa
  3.11.
- Confirmar alcance funcional: el núcleo documentado es Interviewer y Trainer; no asumir como
  entregados los agentes o interfaces descritos como objetivos en documentación más antigua.
- Elegir proveedor LLM, presupuesto por usuario, retención de datos y política de privacidad antes
  de usar conversaciones reales.
- Confirmar si el catálogo pgVector y la base conversacional deben compartir infraestructura o tener
  aislamiento físico, según carga, permisos y recuperación.
- Validar que la calidad de los planes puede medirse con criterios explícitos y casos representativos
  antes de optimizar prompts o cambiar modelos.
