# Job scheduler en la app para avisos y encuestas: plan

Estado: **fases 1 a 6 aplicadas y verificadas con `make tests` (2026-10-07); falta la verificación manual en dev**. Última actualización: 2026-10-07. Rama: `feature/metrics`.
Relacionado: [evaluation-estado.md](evaluation-estado.md), [encuestas-satisfaccion.md](../encuestas-satisfaccion.md).

## Progreso por fases

| Fase | Estado |
|---|---|
| 1. Esquema y dominio | aplicada y verificada con `make tests` |
| 2. Repositorio de jobs | aplicada y verificada con `make tests` |
| 3. Registro al crear el ciclo | aplicada con escritura doble (colas antiguas + jobs); el aviso por interacción pasa a jobs en la fase 4 |
| 4. Scheduler y `SchedulerSettings` | aplicada y verificada con `make tests` (workers, tests antiguos y servicios de los 4 composes eliminados; `--remove-orphans` en `dev-up`/`prod-up`; `.env.example` y docs actualizados) |
| 5. Migración de datos y limpieza del esquema | aplicada: migraciones reescritas (`c2d8…` esquema, `e5c7…` datos, `a7d3…` retira `training_notifications`), modelos antiguos eliminados y `test_job_migration.py` verificado contra Postgres 16. Flags por tipo eliminados (`scheduler_enabled` activa todo) |
| 6. Documentación final | aplicada: README (árbol), AGENTS.md, `scheduler.md`, `modelo-datos.md`, `entornos-y-despliegue.md`, `how-to.md` y `.env.example` revisados contra el repo |

Decisiones tomadas en la fase 4 (sustituyen a lo que diga el resto del plan):
- Configuración: `scheduler_enabled` (false) e `interval_seconds` comunes; los flags `training_reminders_enabled`
  y `evaluation_enabled` mantienen su nombre; reintentos, lease y lote siguen por tipo con sus prefijos actuales
  (`training_reminder_*`, `evaluation_*`) y sin `*_interval_seconds`.
- Atomicidad de la encuesta: `save_sent` hace flush y `finish` confirma ambas cosas en el mismo commit.
- `--once` desaparece. Se aceptan los cambios de comportamiento 1, 2, 5 y 6.
- El aviso por interacción pasa a jobs en esta fase; `ReminderDelivery.id` es UUID.

Decisiones tomadas en la fase 5 (sustituyen a lo que diga el resto del plan):
- No se crean las 3 revisiones del plan original: ninguna de `c2d8`, `d9a1`, `e5c7` y `a7d3` se aplicó en ninguna base, así que
  se reescriben. `a41bc08d732e` ya está en `develop` (desplegada), por lo que `training_notifications` se retira en `a7d3`.
- Las encuestas no enviadas no se traspasan (la tabla de cola nunca existió en ninguna base); sí las notificaciones.
- Ancla de la renovación: `started_at` del ciclo. Cambios de comportamiento 1, 2, 5 y 6 aceptados.
- Configuración: `scheduler_enabled` activa todos los tipos de job y el intervalo es común; desaparecen los flags por tipo.

## Decisiones cerradas

- Scheduler como tarea asyncio en el lifespan de la app (no `sched`, no APScheduler, sin contenedores aparte).
- La ejecución del scheduler es común; cada tipo de job lleva su `execution_date` precalculada al crear el mesociclo.
- `training_notifications` y las columnas de cola de `training_evaluation` se eliminan en este cambio (no están en `main`).
- 4 encuestas (días 7, 14, 21, 28) + 1 aviso (fin del ciclo) por mesociclo.
- Posponer solo reprograma el aviso.
- Encuesta sin respuesta: pasa a `unanswered` y se cierra en Telegram solo cuando se lanza la siguiente.
- Voto tardío sobre una encuesta `unanswered`: se ignora y se registra en el log.

## Puntos abiertos

Ninguno: el ancla de la renovación (`started_at`), la configuración común `scheduler_*` y los cambios de
comportamiento 1, 2, 5 y 6 quedaron validados el 2026-10-06. `make tests` pasa completo (1019 tests, cobertura 91 %). Falta la verificación
manual en dev (ensayo de la migración sobre una copia de la BD de dev con `pg_dump`).

---

## Contexto

Hoy hay dos contenedores worker (`training_reminders`, `evaluation`) con dos colas distintas:
- **Avisos**: `training_notifications`. El worker detecta en cada tick los ciclos vencidos (`enqueue_due`),
  los reclama (`claim_reminder`) y envía `TRAINING_DUE_MESSAGE`. Además, `remind_on_interaction` envía el
  aviso en línea cuando el usuario escribe con el ciclo vencido (`reserve_interaction_reminder`).
- **Encuestas**: `training_evaluation` es cola y resultado. Se programan 4 filas al dar fecha al ciclo.

Objetivo: **un solo scheduler dentro de la app** que lee una tabla genérica de jobs y despacha cada tipo
a su método. Los jobs se registran **al crear el plan** con su `execution_date` precalculada. Se retiran
los contenedores. Funcionalidad idéntica salvo lo listado en "Cambios de comportamiento".

Decidido: tarea asyncio en el lifespan (no `sched`: es síncrono y su cola en memoria duplica la
tabla), ejecución del scheduler común, y eliminar `training_notifications` y las columnas de cola de
`training_evaluation` en este mismo cambio (no están en `main`).

## Análisis: qué es genérico y qué es resultado

| Columna actual de `training_evaluation` | Destino | Por qué |
|---|---|---|
| `due_at` | `job_execution.execution_date` | Cuándo ejecutar: lo necesita cualquier job |
| `state` (pending/sending/…) | `job_execution.state` | Ciclo de vida de ejecución, común |
| `locked_until` | `job_execution.locked_until` | Lease: evita doble ejecución entre réplicas y recupera tras caída. Lógica idéntica, pero genérica |
| `attempts` | `job_execution.attempts` | Reintentos con `RetryPolicy`, común |
| `chat_id` | Ambas | Destinatario del job y dueño del resultado |
| `mesocycle_id`, `week_number` | `payload` del job **y** columnas del resultado | El job los necesita para ejecutar; el resultado para medir |
| `plan_id`, `goal`, `telegram_poll_id`, `telegram_message_id`, `score`, `sent_at`, `answered_at` | `training_evaluation` | Resultado propio de la encuesta |
| (nuevo) `job_id` | `training_evaluation` | Trazabilidad: qué job produjo la encuesta |

**Propuesta**: la lógica de `locked_until` se conserva tal cual, pero vive en el job (el reclamo, el lease y
la comprobación de propiedad al terminar son iguales para cualquier tipo). `training_evaluation` pasa a
contener solo encuestas **enviadas** (se inserta al enviar, con su `job_id`); los intentos
fallidos/cancelados quedan en `job_execution`.

## Diseño

### Tabla `job_execution` (modelo `JobExecutionRecord` en `models.py`)
`id` UUID PK (`job_id`) · `job_type` (`training_reminder` | `evaluation_poll`) · `chat_id` BigInteger ·
`payload` JSONB (`{"mesocycle_id": …, "week_number": …}`) · `dedup_key` UNIQUE
(`evaluation_poll:{cycle}:{week}`, `training_reminder:{cycle}:{n}`; sustituye a los UNIQUE actuales) ·
`state` (`pending`/`running`/`done`/`failed`/`cancelled`) · `execution_date` · `locked_until` · `attempts` ·
`created_at` · `executed_at` (fecha de ejecución finalizada; se rellena en done/failed y en la cancelación
que decide el propio job). Índices: parcial `(execution_date) WHERE state IN ('pending','running')` y `chat_id`.
Uso `state` en lugar de un booleano `executed` porque hace falta distinguir hecho, fallido, cancelado y reintento.
`payload` en vez de FK a mesociclos: así la tabla sirve para jobs futuros, y cada handler ya valida en la
ejecución que el ciclo sigue vigente.

### Dominio y puertos
- `domain/scheduled_job.py`: `JobType`, `JobState`, `ClaimedJob`, `JobOutcome` (done | retry_at | failed | cancelled).
- `repository/job_repository.py`: `JobRepository` (`claim(now, lock_timeout, types)`, `finish(job, outcome)`,
  `JobConflictError`). El puerto `EvaluationRepository` se reduce a lo que usa el handler (`open_current_plan`,
  `previous_unanswered`, `save_sent`) y `record_answer` (sin cambios).

### Calendario
- **5 jobs por mesociclo**: 4 `evaluation_poll` (días 7, 14, 21 y 28) + 1 `training_reminder` en `expected_end_at`
  (día 28; vence el mismo día que la semana 4).
- **Ancla = `started_at` del ciclo**, que se fija una sola vez al crear el ciclo: en el primer plan es el
  momento de generación; en una renovación, la fecha de inicio aceptada. Verificado en el código: ninguna operación
  modifica `started_at` de un ciclo ya fechado (`set_start` solo actúa sobre ciclos antiguos sin fecha).
- Cambio de ejercicios (plan nuevo, mismo ciclo): no toca los jobs; la encuesta pregunta por el plan vigente al enviarse.
- Posponer: solo se reprograma el aviso. Las encuestas no se mueven.

### Encuesta sin respuesta
- Nueva columna `training_evaluation.answer_status`: `awaiting` (enviada) | `answered` | `unanswered`.
- Al lanzar una encuesta, la anterior **del chat** (no solo del ciclo; así la semana 4 la cierra la semana 1 del
  ciclo siguiente) que siga en `awaiting` pasa a `unanswered`, y se hace `stopPoll` en Telegram (best effort: si
  falla, se registra un aviso y queda `unanswered` igualmente). Ya no hay otro cierre.
- `record_answer`: solo acepta votos en `awaiting` → `answered`. Si llega un voto a una encuesta `unanswered`, se
  ignora y se registra en el log.
- Migración de datos: las enviadas con `score` pasan a `answered`; las enviadas sin `score` y con una posterior del
  chat ya enviada pasan a `unanswered`; la última sin `score`, a `awaiting`.

### Registro de jobs (al crear el ciclo)
`infrastructure/database/postgres_job_repository.py`, sustituye a `schedule_evaluations`/`cancel_pending_evaluations`:
- `schedule_cycle_jobs(session, cycle, now)`: 4 encuestas futuras (`upcoming_polls`, se reutiliza) + 1 aviso
  en `expected_end_at`. Se llama donde hoy se llama `schedule_evaluations`: `save_training_plan`,
  `accept` (renovación) y `set_start`. Misma transacción (outbox), `ON CONFLICT (dedup_key) DO NOTHING`.
- `cancel_pending_jobs(session, *criteria)`: `close_cycle` (por ciclo) y `restart_interview` (por chat).
- `postpone`: cancela el aviso pendiente del ciclo y registra uno nuevo en `until` (ya no hace falta el truco
  de la ocasión 0 cancelada).
- `set_reminders(on)`: si el ciclo no tiene aviso pendiente/en curso ni uno hecho para su `expected_end_at`
  actual, registra uno (hoy `enqueue_due` lo crea en el siguiente tick al reactivar).
- `reserve_interaction_reminder`/`finish_reminder`: misma firma en el puerto, pero reclaman el job de aviso
  vencido del ciclo (lease fijo de 2 min, como hoy). `ReminderDelivery.id` pasa a UUID.
- Se eliminan `enqueue_due`, `claim_reminder` y `PostgresEvaluationRepository.claim/mark_sent/finish`.

### Scheduler (`infrastructure/jobs/scheduler.py`)
`JobScheduler` con `run(stop)`, `tick()` y un mapa `JobType -> método`:
- `_run_training_reminder`: comprobaciones actuales de `claim_reminder` (ciclo vigente, avisos activos, no
  cerrado, vencido, sin workflow abierto); si no se cumplen, `cancelled`. Envía `TRAINING_DUE_MESSAGE`.
- `_run_evaluation_poll`: ciclo y plan vigentes (si no, o si está superado por `due_week`, `cancelled`);
  la anterior del chat en `awaiting` pasa a `unanswered` + `stopPoll` (best effort); `sendPoll`; inserta
  `training_evaluation` (`awaiting`) y marca el job `done` en la misma transacción. Se mueven aquí
  `poll_question` y `_close_previous`.
- Fallos de Telegram: `classify_failure` (se mantiene `telegram_delivery.py`) → `retry_at`/`failed`.
- Por tick: reclama hasta `batch_size` jobs de los tipos activos, ordenados por `execution_date`; una sesión
  por tick; `SQLAlchemyError` se registra y se sigue en el siguiente tick.
- Se borran `training_reminders.py`, `evaluation.py` y `worker_loop.py` (con sus tests).
- `main.py` lifespan: valida `SchedulerSettings` (fail fast) y, si `scheduler_enabled`, crea la tarea; al
  apagar activa el evento de parada y la espera antes de `close_database`.
- Varias réplicas de la app: seguro gracias a `FOR UPDATE SKIP LOCKED` + `locked_until`.

### Configuración (`SchedulerSettings`, prefijo `scheduler_`)
`enabled` (true), `interval_seconds` (300, ≥10), `batch_size`, `max_attempts`, `retry_delay_seconds`,
`retry_max_delay_seconds`, `lock_timeout_seconds` (antes `sending_timeout`), con los mismos valores por
defecto y validaciones; `to_retry_policy()` se conserva. Flags por tipo con los nombres actuales
(`training_reminders_enabled`, `evaluation_enabled`, por defecto false): un tipo desactivado no se reclama
y sus jobs siguen pendientes, como hoy. Se eliminan `TrainingSettings`, `EvaluationSettings` y
`_RetrySettings`; `webhook.py` toma `max_attempts` del scheduler.
**Hay que actualizar los `.env` reales**: desaparecen `training_reminder_*` y `evaluation_*` (salvo
los dos flags) y aparecen `scheduler_*`. Se documentan en `.env.example`.

### Migraciones Alembic (3 revisiones, datos separados de esquema)
1. Esquema: crea `job_execution` y añade `training_evaluation.job_id` (FK SET NULL) y `answer_status`.
2. Datos: encuestas no enviadas → jobs `evaluation_poll` (mismo estado/fecha/intentos) y se borran esas filas;
   notificaciones `pending`/`sending` → jobs `training_reminder`; ciclos abiertos con fecha y sin ninguna
   notificación → job de aviso en `expected_end_at` (lo que haría `enqueue_due`).
3. Esquema: elimina `training_notifications`, las columnas `due_at`/`state`/`locked_until`/`attempts` y el
   índice `ix_training_evaluation_due`. El downgrade recrea la estructura, no los datos.

### Contenedores, Makefile y CI
- Quitar los servicios `training-reminders*` y `evaluation*` de los 4 composes; en el de tests,
  `scheduler_enabled=false` en la app (los IT ejecutan `tick()` en proceso, sin carreras).
- `prod-up` y `dev-up` con `--remove-orphans`, para que el despliegue elimine los contenedores antiguos
  (el proyecto `fitcoach-prod` es exclusivo, así que es seguro).

## Cambios de comportamiento (a validar)
1. Un `TelegramError` inesperado ya no detiene el proceso (sería tumbar la app): el job queda `failed` con log ERROR.
2. Desaparece `--once` (`docker compose run … --once`).
3. El aviso se registra al crear el plan, no lo descubre un sondeo; el resultado para el usuario es el mismo.
4. `training_evaluation` solo guarda encuestas enviadas; el histórico de fallidas/canceladas está en `job_execution`.
5. Nuevo estado `unanswered`; un voto tardío sobre una encuesta cerrada se ignora (hoy se guardaría).
6. La encuesta pendiente se cierra también entre ciclos (hoy solo dentro del mismo ciclo).

## Ficheros principales
`infrastructure/database/{models,postgres_job_repository (nuevo),postgres_evaluation_repository,postgres_training_repository,postgres_conversation_repository}.py`,
`infrastructure/jobs/scheduler.py` (nuevo), `infrastructure/config/settings.py`, `main.py`, `api/webhook.py`,
`domain/scheduled_job.py` (nuevo), `repository/{job_repository (nuevo),evaluation_repository,training_repository}.py`,
`alembic/versions/` (3 nuevas), los 4 composes, `Makefile`, `.env.example`.

## Tests (OK y KO en cada nivel)
- Unitarios: `test_scheduler.py` (despacho por tipo, tipo desactivado, reintento/fallo/cancelación, error de BD
  en un tick, parada), `test_settings.py` (`SchedulerSettings`), `test_main.py` (arranca y para la tarea;
  sin tarea si está desactivado), `test_training_service.py` (aviso por interacción).
  Se eliminan `test_evaluation_worker.py`, `test_training_reminders.py` y `test_worker_loop.py`.
- IT: `test_job_repository.py` (registro idempotente, claim con SKIP LOCKED, lease caducado, conflicto al
  terminar), adaptar `test_evaluation_repository.py`, `test_training_repository.py`, `test_evaluation_flow.py`
  (`tick()` en proceso contra el stub) y `test_training_migration.py`; nuevo `test_job_migration.py`
  (migración de datos con pendientes, enviadas y ciclos sin notificación; downgrade).

## Documentación
Nuevo `docs/scheduler.md` (tabla, ciclo de vida, cómo añadir un tipo de job, configuración) y añadirlo al
índice. Actualizar `encuestas-satisfaccion.md`, `trainer-agent.md` (Fechas y avisos, Persistencia),
`modelo-datos.md`, `entornos-y-despliegue.md`, `how-to.md` (variables), `Makefile.md`, `README.md`
(árbol y composes), `AGENTS.md` (secciones 1 y 8) y `docs/todo/evaluation-estado.md`.

## Verificación
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run pytest tests/unit_test --no-cov`,
`pre-commit run --all-files` y `make tests` (necesita Docker).
Manual en dev: `make dev-up` → `/train` → consultar `job_execution` (5 filas) → adelantar `execution_date`
y comprobar que llegan el poll y el aviso y que el job queda `done` con `executed_at`.
