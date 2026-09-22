# Plan de implementación del agente `trainer`

## Objetivo

Añadir el **Agente 2 (Entrenador)** siguiendo la misma estructura que el agente
`interviewer` ya existente. El agente no entrevista: parte del perfil que el
`interviewer` dejó en `interviewer_profiles` para el `chat_id` de Telegram,
recupera ejercicios de la base de datos vectorial (`infra/vector-db`, imagen
pgVector) y pide al LLM un mesociclo de 4 semanas validado contra un contrato
Pydantic estricto.

## Decisiones tomadas

| Decisión | Valor | Motivo |
|---|---|---|
| Disparador | Comando `/train` | Explícito, permite regenerar, aísla el agente para tests. |
| Interacción | One-shot + preguntas posteriores | Una llamada genera el plan; después el usuario puede preguntar o pedir ajustes. |
| Embeddings de consulta | Servicio `embedder` independiente | `metadata_vector` es `vector(384)` de `all-MiniLM-L6-v2`; hay que usar **el mismo modelo**. Meter `sentence-transformers` en la app arrastraría torch (~2-3 GB) al contenedor del webhook. |
| Orquestación | Cadena propia, como `InterviewerChain` | LangGraph (ver `docs/todo/agentes.md`) queda para cuando existan los 4 agentes; no se adelanta aquí. |

## 1. Flujo de un `/train`

```text
Telegram  ──POST /webhook/response──▶  ConversationService
                                          │
                     ┌────────────────────┴───────────────────┐
                     │ 1. lee interviewer_profiles[chat_id]   │
                     │    (si no existe → mensaje y fin)      │
                     └────────────────────┬───────────────────┘
                                          ▼
                     ┌────────────────────────────────────────┐
                     │ 2. ExerciseRetriever                    │
                     │    a) construye texto de consulta       │
                     │       desde el perfil                   │
                     │    b) embedder: POST /embed → [384]     │
                     │    c) pgVector: prefiltro SQL +         │
                     │       ORDER BY metadata_vector <=> q    │
                     └────────────────────┬───────────────────┘
                                          ▼
                     ┌────────────────────────────────────────┐
                     │ 3. TrainerChain                         │
                     │    system_prompt + SKILL + rag_context  │
                     │    + perfil  →  1 llamada LLM           │
                     │    → TrainerTurn (Pydantic)             │
                     └────────────────────┬───────────────────┘
                                          ▼
                     ┌────────────────────────────────────────┐
                     │ 4. persiste training_plans +            │
                     │    training_sessions + token_usage      │
                     │ 5. envía `report` por Telegram          │
                     └────────────────────────────────────────┘
```

Mensajes posteriores con `training_sessions.status = 'active'` van al modo
preguntas: mismo `TrainerChain`, historial propio del agente y el plan vigente
inyectado como contexto.

## 2. Infraestructura

### 2.1 Servicio `embedder` (nuevo)

```text
infra/embedder/
  Dockerfile-embedder        # python:3.11-slim + sentence-transformers
  app.py                     # FastAPI: POST /embed, GET /health
  requirements.txt           # fastapi, uvicorn, sentence-transformers
  .env.embedder.example
```

- `POST /embed` recibe `{"texts": ["..."]}` y devuelve `{"vectors": [[384 floats]]}`.
- El modelo (`sentence-transformers/all-MiniLM-L6-v2`) se **descarga en build**
  (`RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer(...)"`)
  para que el arranque no dependa de HuggingFace ni de la red.
- `GET /health` responde solo cuando el modelo está cargado; el compose usa esa
  sonda en su `healthcheck`.
- El nombre del modelo es configurable por env (`EMBEDDER_MODEL`) pero **debe
  coincidir** con el de `infra/vector-db/loader/loader.py:177`; si cambia, hay
  que re-vectorizar todo el corpus y regenerar el volcado.

### 2.2 Arreglos necesarios en `infra/vector-db`

Tres problemas bloquean la conexión desde la app y deben resolverse antes:

1. `docker-compose.vector-db.yml` declara `name: fitcoach-prod`, **el mismo
   nombre de proyecto que `docker-compose.yml`**. Levantar ambos hace que
   Compose los trate como un único proyecto y se pisen. Renombrar a
   `fitcoach-vector-db`.
2. `pgvector` solo está en la red `fit-coach-net`; la app vive en
   `proxy-network`. Añadir `proxy-network` a las redes del servicio `pgvector`
   (ya está declarada como externa en ese fichero, pero no se usa).
3. El volumen `fitcoach_prod_pgvector` está declarado y no se usa: eliminarlo.

Además, crear un rol **de solo lectura** para la app, como
`infra/vector-db/ddl/002_<fecha>_readonly-role.sql`:

```sql
CREATE ROLE fitcoach_ro LOGIN PASSWORD :'pwd';
GRANT CONNECT ON DATABASE fitcoach TO fitcoach_ro;
GRANT USAGE ON SCHEMA public TO fitcoach_ro;
GRANT SELECT ON public.exercises, public.exercise_media TO fitcoach_ro;
```

La app nunca escribe en esta base de datos.

> Nota de seguridad: `001_..._part-01.sql` incluye el hash SCRAM del rol
> `fitcoach` en el repositorio. No es texto plano, pero es atacable offline.
> Conviene rotar esa contraseña en los entornos reales y no reutilizarla.

### 2.3 Composes

- `docker-compose.dev.yml`: añadir el servicio `embedder-dev` y las variables
  `embedder_url` y `vector_database_url` al servicio de la app, con
  `depends_on: embedder-dev: {condition: service_healthy}`.
- `docker-compose.yml` (prod): equivalente, con `restart: unless-stopped`.
- `Makefile`: targets `vector-up`, `vector-down`, `vector-logs` para
  `infra/vector-db/docker-compose.vector-db.yml`, en la línea de `dev-up`/`prod-up`.

## 3. Configuración

En `src/fitcoach/infrastructure/config/settings.py`:

```python
class VectorDatabaseSettings(BaseSettings):   # env_prefix="vector_database_"
    url: str        # postgresql+asyncpg://fitcoach_ro:...@pgvector:5432/fitcoach

class EmbedderSettings(BaseSettings):         # env_prefix="embedder_"
    url: str
    timeout_seconds: int = 10
```

Y en `IASettings` (prefijo `ia_`):

| Variable | Defecto | Uso |
|---|---|---|
| `ia_trainer_skill` | `trainer` | Skill que se inyecta en el prompt del entrenador. |
| `ia_trainer_max_tokens` | `4096` | Un mesociclo completo no cabe en el `ia_max_tokens` de la entrevista. |
| `ia_rag_top_k` | `8` | Ejercicios recuperados por grupo muscular. |
| `ia_trainer_history_window_messages` | `10` | Historial del modo preguntas. |

`main.py` valida las nuevas settings en el `lifespan` (fail fast), igual que ya
hace con `get_ia_settings()` y `get_database_settings()`.

Actualizar `.env.example` y `docs/how-to.md` con todas ellas.

## 4. Cambios en código

### 4.1 Refactor previo (habilita el reuso, sin cambiar comportamiento)

| Cambio | Ficheros |
|---|---|
| `domain/interviewer_errors.py` → `domain/agent_errors.py`, con `AgentError`/`AgentErrorCode`. Los **valores string se mantienen idénticos** para no invalidar filas de `token_usage` ni los paneles de Grafana. | 4 imports a actualizar: `interviewer_chain.py`, `conversation_service.py`, `test_interviewer_chain.py`, `test_conversation_service.py` |
| Extraer `service/agent/llm_chain.py` con `BaseLLMChain`: `_invoke`, `_extract_usage`, `_error_for_exception`, `_status_error`, `_to_langchain_messages` y un `_validate_or_repair(raw, model_cls)` genérico (la reparación JSON de una pasada, hoy embebida en `InterviewerChain`). | `interviewer_chain.py` pasa a ser una subclase delgada |
| `conversation_messages` necesita una columna `agent` (`String(32)`, default `'interviewer'`) e índice `(chat_id, agent, id)`. Sin ella, el modo preguntas del entrenador heredaría el historial de la entrevista. | `models.py`, repositorio, migración |

### 4.2 Dominio

- `domain/agents.py`: añadir `TrainerAgent(Agent)` (el valor `AgentType.TRAINER`
  ya existe).
- `domain/trainer_plan.py` (nuevo), estricto como `interviewer_profile.py`:

```python
class PlannedExercise(PlanModel):
    exercise_id: int            # FK lógica a exercises.id de la BD vectorial
    name: str
    sets: int; reps: str; rest_seconds: int
    rpe: float | None; notes: str | None

class TrainingDay(PlanModel):
    day: int; focus: str
    exercises: list[PlannedExercise]
    estimated_minutes: int

class TrainingWeek(PlanModel):
    week: int                   # 1..4
    intensity: Literal["accumulation", "intensification", "peak", "deload"]
    days: list[TrainingDay]

class TrainingPlan(PlanModel):
    goal: Literal["lose_fat", "gain_muscle", "performance"]
    days_per_week: int
    environment: Literal["gym", "home", "outdoors", "mixed"]
    weeks: list[TrainingWeek]                 # exactamente 4
    excluded_by_injury: list[str]
    progression_notes: str

class TrainerTurn(PlanModel):
    status: Literal["plan", "answer"]
    reply: str                   # siempre: mensaje listo para Telegram
    report: str | None           # solo en "plan"
    plan: TrainingPlan | None    # solo en "plan"
```

Validadores: `weeks` tiene 4 semanas numeradas 1-4 sin huecos;
`len(days) == days_per_week`; `status == "plan"` exige `plan` y `report`, y
`status == "answer"` los prohíbe (mismo patrón que `InterviewerTurn`).

**Validación cruzada obligatoria:** cada `exercise_id` debe pertenecer al
conjunto recuperado. Si el modelo inventa ejercicios, se rechaza el turno y se
pide la reparación. Esto es lo que impide que el plan se salga de la base de
datos de ejercicios.

### 4.3 Recuperación (RAG)

```text
src/fitcoach/repository/exercise_repository.py        # Protocol
src/fitcoach/infrastructure/vectordb/__init__.py
src/fitcoach/infrastructure/vectordb/session.py       # engine/sessionmaker propios
src/fitcoach/infrastructure/vectordb/models.py        # Exercise (solo lectura)
src/fitcoach/infrastructure/vectordb/pgvector_exercise_repository.py
src/fitcoach/infrastructure/ia/embedder_client.py     # Protocol Embedder + cliente httpx
src/fitcoach/service/agent/rag_context.py             # ejercicios → bloque {{rag_context}}
```

- Motor **separado** del de la app (`get_vector_engine`), con su propio
  `sessionmaker`; jamás se mezclan sesiones ni transacciones.
- Añadir la dependencia `pgvector>=0.3` (paquete Python puro, sin torch) para el
  tipo `Vector(384)` y `cosine_distance()` en SQLAlchemy.
- Consulta: prefiltro SQL barato por `equipment` (derivado de
  `training.equipment` / `training.environment`) y exclusiones por
  `injuries[].restriction`; dentro de ese subconjunto, orden semántico:

```sql
SELECT id, name, category, body_part, equipment, muscle_group, target,
       secondary_muscles, instructions_en
FROM exercises
WHERE (:equipment IS NULL OR equipment = ANY(:equipment))
ORDER BY metadata_vector <=> :query_vector
LIMIT :top_k
```

- El texto de consulta se construye con el **mismo formato** que
  `build_metadata_text()` del loader (`name: ... | category: ... | ...`), para
  que la consulta viva en el mismo espacio semántico que el corpus.
- `rag_context.py` acota el bloque: top-k por grupo muscular, instrucciones
  truncadas y caracteres de control eliminados. El contenido de `exercises` es
  **dato**, no instrucción — el prompt ya lo declara así, pero el constructor
  tampoco debe reinyectar nada que parezca una orden.

**Degradación:** si el embedder o pgVector no responden:

- en `/train` se **falla** con un mensaje amable de reintento (un mesociclo sin
  catálogo de ejercicios no cumple el objetivo del agente);
- en el modo preguntas se degrada a `rag_context` vacío, se registra
  `rag.degraded=true` en el span y se continúa.

### 4.4 Cadena y prompts

```text
src/fitcoach/service/agent/trainer_chain.py
src/fitcoach/infrastructure/prompts/trainer/system_prompt.txt
src/fitcoach/infrastructure/ia/skills/trainer/SKILL.md
src/fitcoach/infrastructure/ia/skills/trainer-dev/SKILL.md
```

- `agent_factory.build_trainer_agent(loader=None, skill_name="trainer")`, gemelo
  del de interviewer. `PromptLoader` ya es genérico: no necesita cambios.
- `system_prompt.txt` replica la estructura del de interviewer: ROLE, MISSION,
  SKILL (`{{skill_content}}`), KNOWLEDGE GROUNDING (`{{rag_context}}`), TONE,
  GUARDRAILS y APPLICATION OUTPUT con el contrato JSON estricto de `TrainerTurn`.
- `SKILL.md` (fuente de verdad del método): periodización de 4 semanas
  (acumulación → intensificación → pico → descarga), volumen a partir de
  `initial_calculations.tolerable_volume_sets`, reparto según
  `commitment.days_per_week` y `minutes_per_session`, sustituciones por lesión y
  esquema de salida. Límites de seguridad: no diagnostica, no prescribe y deriva
  a un profesional ante `flags.red`.
- `trainer-dev/SKILL.md`: variante reducida (1 semana desarrollada y 3
  derivadas) para probar el flujo sin gastar 4096 tokens por iteración, igual
  que `interviewer-dev`. `docker-compose.dev.yml` fija `ia_trainer_skill=trainer-dev`.
- `TrainerChain(BaseLLMChain)` expone `generate_plan(profile, exercises)` y
  `answer(question, plan, history, exercises)`; ambas devuelven
  `TrainerReply(turn, token_usages)`.

### 4.5 Persistencia

Migración Alembic nueva (`down_revision` = el head vigente; comprobar con
`alembic heads`):

```python
op.add_column("conversation_messages",
              sa.Column("agent", sa.String(32), nullable=False,
                        server_default="interviewer"))
op.create_index("ix_conversation_messages_chat_id_agent_id",
                "conversation_messages", ["chat_id", "agent", "id"])

op.create_table("training_plans",
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("chat_id", sa.BigInteger, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("plan", sa.JSON, nullable=False),
    sa.Column("report", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True),
              server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    sa.UniqueConstraint("chat_id", "version"))

op.create_table("training_sessions",
    sa.Column("chat_id", sa.BigInteger, primary_key=True),
    sa.Column("status", sa.String(16), nullable=False),     # generating | active
    sa.Column("current_plan_id", sa.Integer,
              sa.ForeignKey("training_plans.id", ondelete="SET NULL")),
    sa.Column("started_at", ...), sa.Column("updated_at", ...))
```

Se versiona el plan en vez de sobrescribirlo: un `/train` repetido crea la
versión N+1 y el histórico queda disponible para el Agente 3 (Nutricionista),
que necesitará el volumen de entrenamiento.

`restart_interview` debe borrar también `training_sessions` y `training_plans`
del chat: un perfil nuevo invalida el plan anterior.

Métodos nuevos en `ConversationRepository` (Protocol) y en
`PostgresConversationRepository`:

- `get_interviewer_profile(chat_id) -> InterviewerProfile | None`
- `get_training_status(chat_id) -> str | None`
- `get_current_plan(chat_id) -> StoredTrainingPlan | None`
- `save_training_plan(chat_id, plan, report, user_content, assistant_content) -> int`
- `add_turn(...)` y `get_recent(...)` reciben un parámetro `agent: str`
  (por defecto `"interviewer"`, para no romper las llamadas existentes).

### 4.6 Orquestación en `ConversationService`

- `domain/telegram.py`: `TRAIN = ("/train", "Genera tu plan de entrenamiento de 4 semanas")`.
- `bot_telegram_commands` en `.env.example` y en los entornos: añadir
  `train:Tu plan de entrenamiento`.
- `Constants`: `NO_PROFILE_MESSAGE` ("necesito tu entrevista primero, usa
  /interview"), `PLAN_GENERATING_MESSAGE`, `TRAINER_ERROR_MESSAGE` y
  `NO_PLAN_MESSAGE`.
- Tabla de enrutado del mensaje sin comando:

| `interview_sessions.status` | `training_sessions.status` | Destino |
|---|---|---|
| `null` | — | arranca entrevista (comportamiento actual) |
| `in_progress` | — | interviewer (actual) |
| `completed` | `null` | mensaje: "usa /train para tu plan" |
| `completed` | `active` | trainer, modo preguntas |

  Esto sustituye al `INTERVIEW_COMPLETED_MESSAGE` incondicional de hoy
  (`conversation_service.py:143`): es un cambio de comportamiento y hay que
  documentarlo.
- `/train` sin perfil → `NO_PROFILE_MESSAGE`. Con perfil → genera el plan.
- El span `conversation.turn` marca `agent=trainer` y añade los atributos
  `rag.exercises_retrieved`, `rag.latency_ms` y `rag.degraded`.
- `_record_token_usage` pasa a recibir el agente en lugar de fijar
  `AgentType.INTERVIEWER.value` (`conversation_service.py:256`).

### 4.7 Wiring

`webhook.py`: nuevas dependencias `get_trainer_chain`, `get_exercise_repository`
(sesión de la BD vectorial) y `get_embedder_client`, inyectadas en
`ConversationService`. `get_conversation_service` crece; conviene agruparlas en
un pequeño `TrainerDeps` para no dejar la firma con ocho parámetros.

## 5. Tests

Todo test unitario corre **sin Docker, sin red y sin LLM**. Se mantiene el
umbral de cobertura del 80 % (`pyproject.toml`).

### 5.1 Unitarios nuevos

| Fichero | Casos |
|---|---|
| `test_trainer_plan.py` | 4 semanas exactas y numeradas; `days` == `days_per_week`; `status="plan"` exige `plan`+`report`; `status="answer"` los prohíbe; enums inválidos rechazados. |
| `test_trainer_chain.py` | Prompt compuesto (system + rag + perfil); plan válido; reparación JSON de una pasada; rechazo cuando un `exercise_id` no está en el conjunto recuperado; captura de `TokenUsage` incluida la llamada de reparación; mapeo de cada excepción de OpenAI a su `AgentErrorCode`. |
| `test_rag_context.py` | Formato del bloque; truncado de instrucciones; top-k respetado; caracteres de control eliminados; lista vacía → bloque vacío sin romper. |
| `test_embedder_client.py` | Con `httpx.MockTransport`: respuesta correcta; dimensión distinta de 384 → error; timeout → `AgentError(UNAVAILABLE)`; 5xx → error reintentable. |
| `test_pgvector_exercise_repository.py` | Con `AsyncMock` de sesión: la SQL lleva el `ORDER BY ... <=> ...`, el `LIMIT` es `top_k` y el prefiltro de equipamiento se aplica solo si hay equipamiento. |
| `test_llm_chain.py` | `BaseLLMChain` en aislamiento: `_invoke`, `_extract_usage` (ambas formas) y `_validate_or_repair` con un modelo Pydantic de juguete. |

### 5.2 Unitarios a ampliar

- `test_conversation_service.py`: `/train` sin perfil; `/train` con perfil → plan
  enviado y persistido; regeneración crea la versión N+1; enrutado del mensaje
  libre según la tabla de 4.6; fallo del embedder en `/train` → mensaje de
  reintento y nada persistido; `token_usage` registrado con `agent="trainer"`.
- `test_agents.py` / `test_agent_factory.py`: `TrainerAgent`,
  `build_trainer_agent` e `insert_context` sobre el prompt del entrenador.
- `test_settings.py`: nuevas settings y su fallo cuando faltan.
- `test_webhook.py`: las nuevas dependencias se resuelven y se inyectan.
- `test_main.py`: el `lifespan` aborta si falta `vector_database_url` o
  `embedder_url`.

### 5.3 Integración

`tests/docker-compose-test.yml` gana dos servicios:

- `pgvector-test`: imagen `pgvector/pgvector:pg18-trixie` **sin el volcado real**
  (283 MB y varios minutos de arranque). Se carga
  `tests/fixtures/exercises_min.sql`: el mismo DDL más una decena de ejercicios
  con vectores de 384 dimensiones deterministas.
- `embedder-stub`: contenedor mínimo que devuelve un vector fijo. Evita
  descargar el modelo en CI y hace el test reproducible.

`tests/it/test_trainer_flow.py`: perfil insertado en `interviewer_profiles`,
`/train`, y se comprueba que la respuesta llega, que `training_plans` tiene una
fila y que todos los `exercise_id` del plan existen en `exercises`.

> El volcado real solo se ejercita a mano (`make vector-up`); no entra en CI.

## 6. Documentación

| Documento | Acción |
|---|---|
| `docs/trainer-agent.md` | **Nuevo**, espejo de `docs/interviewer-agent.md`: flujo, contrato JSON, tablas, errores, configuración y componentes. |
| `docs/vector-db.md` | **Nuevo**: esquema de `exercises`/`exercise_media`, modelo de embeddings y por qué no se puede cambiar sin re-vectorizar, cómo levantar pgVector y pgAdmin, cómo consultar, rol de solo lectura. |
| `docs/embedder.md` | **Nuevo** (o sección dentro de `vector-db.md`): contrato del servicio, healthcheck, tamaño de imagen, cómo cambiar de modelo. |
| `docs/interviewer-agent.md` | Actualizar: el mensaje "entrevista completada" ya no es el final del camino; ahora apunta a `/train`. |
| `docs/how-to.md` | Nuevas variables de entorno, `make vector-up`, cómo probar `/train` en dev. |
| `docs/queries-reference.md` | Consultas de `token_usage` y coste desglosadas por `agent`. |
| `README.md` | Árbol de proyecto con `infra/embedder/` e `infrastructure/vectordb/`; el Agente 2 deja de estar pendiente. |
| `.env.example` | `vector_database_url`, `embedder_url`, `embedder_timeout_seconds`, `ia_trainer_*`, `ia_rag_top_k` y el comando `train`. |

## 7. Orden de trabajo sugerido (una PR por bloque)

1. **Refactor sin funcionalidad nueva**: `agent_errors`, `BaseLLMChain` y la
   columna `agent` en `conversation_messages` con su migración. Los tests
   existentes deben pasar sin cambios de comportamiento.
2. **Infraestructura**: servicio `embedder`, arreglos del compose de
   `infra/vector-db`, rol de solo lectura, targets del Makefile, settings y
   validación en el `lifespan`. Verificable con `curl` y `psql`, sin tocar la app.
3. **Recuperación**: `vectordb/`, `embedder_client`, `rag_context` y sus tests.
   Aún sin LLM: ya se puede comprobar que un perfil devuelve ejercicios
   coherentes.
4. **Agente**: `trainer_plan.py`, prompts, `SKILL.md`, `TrainerChain` y tests.
5. **Orquestación y entrega**: `/train`, enrutado, persistencia, tests de
   integración y documentación.

## 8. Riesgos y puntos abiertos

| Riesgo | Mitigación |
|---|---|
| El modelo inventa `exercise_id` que no existen. | Validación cruzada contra el conjunto recuperado más una reparación; si falla, no se persiste nada. |
| Un mesociclo de 4 semanas se corta por `max_tokens`. | `ia_trainer_max_tokens=4096` como suelo; `trainer-dev` para iterar barato; `llm_output_limit` ya tiene mensaje de usuario. |
| Latencia: embedder + pgVector + LLM en un solo update de Telegram. | Enviar `PLAN_GENERATING_MESSAGE` antes de la llamada; el webhook ya responde 200 pase lo que pase. Si se acerca al límite de Telegram, mover la generación a una tarea de fondo (fuera del alcance de este plan). |
| Dos bases de datos PostgreSQL en la app. | Motores y sesiones separados; la vectorial es de solo lectura y nunca participa en una transacción de negocio. |
| Cambiar el modelo de embeddings invalida el corpus. | Documentado en `docs/vector-db.md` y comprobado en arranque: si la dimensión devuelta no es 384, el cliente falla en claro. |

Puntos sin decidir, que conviene cerrar antes del bloque 5:

- ¿El modo preguntas puede **modificar** el plan (nueva versión) o solo
  explicarlo? El plan asume que sí puede, creando la versión N+1.
- ¿Se entrega el plan como texto en Telegram, como fichero, o ambos? De momento,
  `report` en texto; el JSON queda en base de datos para el Agente 3.
- ¿Se aprovechan `exercise_media` (imágenes y GIF) en la respuesta de Telegram?
  Fuera del alcance de este plan, pero la tabla está ahí.
