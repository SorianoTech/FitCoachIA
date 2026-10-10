# Scheduler de jobs

Un solo scheduler dentro de la app (tarea `asyncio` del *lifespan* de FastAPI) ejecuta los avisos de fin de
ciclo y las encuestas semanales. Lee la tabla `job_execution` ([modelo-datos.md](modelo-datos.md)) y despacha
cada tipo de job a su método. Sustituye a los contenedores `training-reminders` y `evaluation`.

## Ciclo de vida de un job

1. **Registro**: al dar fecha a un ciclo (primer plan, renovación aceptada, `set_start`) se insertan, en la misma
   transacción, 4 jobs `evaluation_poll` (semanas 1-4) y 1 `training_reminder` en `expected_end_at`.
   `dedup_key` hace idempotente el registro.
2. **Reclamo**: `PostgresJobRepository.claim` toma el job vencido más antiguo del tipo con `FOR UPDATE SKIP LOCKED`,
   lo pasa a `running`, fija `locked_until` (lease) y suma un intento. Un lease caducado se puede reclamar de nuevo.
3. **Ejecución**: el handler del tipo devuelve un `JobOutcome`: `done`, `retry(retry_at)`, `failed` o `cancelled`.
4. **Cierre**: `finish` valida que el job sigue bloqueado por este scheduler (mismo estado e intentos) y guarda el
   resultado y `executed_at`. Si otro scheduler lo reclamó, lanza `JobConflictError` y no escribe nada.

Cancelan los jobs pendientes: `close_cycle` (por ciclo), `/interview` (por chat) y posponer (solo el aviso, que se
sustituye por otro en la nueva fecha). Un job en curso termina y queda registrado.

## Tipos

| Tipo | Handler | Qué comprueba antes de enviar | Resultado |
|---|---|---|---|
| `training_reminder` | `_run_training_reminder` | Ciclo vigente del chat, avisos activos, no cerrado, vencido y sin flujo abierto | `sendMessage` con `TRAINING_DUE_MESSAGE`; si no aplica, `cancelled` |
| `evaluation_poll` | `_run_evaluation_poll` | Ciclo abierto con plan vigente y semana no superada por otra más reciente | `sendPoll` y fila en `training_evaluation`; si no aplica, `cancelled` |

El aviso por interacción (`remind_on_interaction`) reclama el mismo job de aviso vencido del ciclo con un lease
fijo de 2 minutos, así que el scheduler y la interacción nunca lo envían dos veces.

### Encuestas

- **Atomicidad**: el handler hace `flush` de la fila de `training_evaluation` y el scheduler la confirma en el mismo
  `commit` que marca el job `done`. Si el lease se perdió mientras se enviaba, el `finish` falla, el `rollback`
  descarta la fila y se registra un ERROR (la encuesta ya estaba en Telegram, así que es el único hueco posible).
- **Sin respuesta**: al enviar una encuesta, las anteriores del chat que sigan en `awaiting` pasan a `unanswered` y
  se cierran con `stopPoll` (best effort: si falla, se avisa y queda `unanswered` igualmente). Alcanza también a
  las del ciclo anterior.
- **Voto tardío** sobre una encuesta `unanswered`: se ignora y se registra en el log.
- **Tras una caída** solo se envía la semana más reciente; las anteriores se cancelan.

## Fallos de Telegram

`classify_failure` decide el resultado: `RetryAfter` y `NetworkError` reintentan con la política del tipo (hasta
`max_attempts`), `BadRequest`/`Forbidden` fallan. Un `TelegramError` desconocido deja el job en `failed` con log
ERROR, pero no detiene el scheduler. Un job que supera `max_attempts` tras una interrupción se marca `failed` sin
ejecutarse. Un error de base de datos aborta el tick y se reintenta en el siguiente.

## Logs

Logger `fitcoach.infrastructure.jobs.scheduler`. Cada job deja su id y su tipo, de modo que se puede seguir de
principio a fin filtrando por el id o por `(evaluation_poll)` / `(training_reminder)`:

| Nivel | Mensaje | Cuándo |
|---|---|---|
| INFO | `Job <id> (<tipo>) claimed: chat=… attempt=… due=… payload=…` | Al reclamarlo |
| INFO | `Job <id> (<tipo>) cancelled: <motivo>` | El handler decide no enviarlo (`reminder no longer due`, `no open cycle with a current plan`, `week N is no longer the current one`) |
| INFO | `Job <id> (<tipo>) finished: state=… retry_at=…` | Al registrar el resultado (`done`, `failed`, `cancelled` o `pending` con reintento) |
| WARNING/ERROR | `Job <id> (<tipo>) not delivered to chat …` | Fallo de Telegram (ver arriba) |
| INFO | `Scheduler tick finished: processed=N` | Al final de cada tick |

## Configuración

| Variable | Defecto | Significado |
|---|---|---|
| `scheduler_enabled` | `false` | Arranca la tarea con la app y activa todos los tipos de job; apagado, los jobs siguen pendientes |
| `scheduler_interval_seconds` | `300` (mín. 10) | Intervalo entre ticks, común a todos los tipos |
| `training_reminder_*` / `evaluation_*` | ver `.env.example` | Reintentos (`max_attempts`, `retry_delay_seconds`, `retry_max_delay_seconds`), `sending_timeout_seconds` (lease) y `batch_size`, por tipo |

`main.py` valida los tres grupos al arrancar (fail fast). Las variables `*_interval_seconds` por tipo y los flags `training_reminders_enabled` / `evaluation_enabled` ya no se leen.

## Varias réplicas

Seguro: el reclamo usa `SKIP LOCKED` y el lease, y `finish` rechaza resultados de un lease perdido.

## Cómo añadir un tipo de job

1. Valor en `JobType` y claves de `dedup_key` en `domain/scheduled_job.py`.
2. Handler `async (job, session, policy) -> JobOutcome` en `infrastructure/jobs/scheduler.py` y alta en el mapa
   de `JobScheduler.__init__` con su `RetryPolicy`.
3. Registro del job donde nace (misma transacción) con `schedule_job`, y su cancelación si procede.
4. Settings por tipo, `.env.example`, tests (OK y KO) y esta página.
