# Encuestas de satisfacción (`evaluation`): estado del desarrollo

> **Histórico.** Describe los workers `training_reminders` y `evaluation`, ya sustituidos por el scheduler de la app (ver [job-scheduler-plan.md](job-scheduler-plan.md) y [../scheduler.md](../scheduler.md)).

Rama: `feature/trainer-mesocycle-renewal`. Última actualización: 2026-10-03.
Plan de pruebas: [evaluation-tests.md](evaluation-tests.md).

Reparto acordado: **el desarrollador aplica el código de producción**; Claude describe cada paso con
el código propuesto y escribe los tests, la documentación y `.env.example`.

---

## 1. Requisitos acordados

- Poll de Telegram **no anónimo**, una pregunta: *"Semana {k} de tu plan para {goal}: ¿qué te está
  pareciendo?"* (sin objetivo conocido: *"Semana {k} de tu plan: ¿qué te está pareciendo?"*), con
  6 opciones: "0 - No me ha gustado nada", "1 - No me gusta mucho", "2 - Regular, mejorable",
  "3 - Está bien, puede mejorar", "4 - Me está gustando mucho", "5 - Lo recomiendo sin dudar".
- **4 encuestas por mesociclo**: días 7, 14, 21 y 28 desde `training_mesocycles.started_at` del
  ciclo vigente (`training_sessions.current_plan_id → training_plans.mesocycle_id`).
- Se envían **siempre**: no dependen de `reminders_enabled` ni de `/train avisos off`.
- No se envían si el ciclo no tiene `started_at` o está cerrado (`completed_at`).
- Aplazar no genera encuestas extra.
- Worker caído: al volver se envía **solo la semana más reciente**; las anteriores pendientes se cancelan.
- Sin respuesta: no se reenvía; se pregunta la semana siguiente. **El poll anterior sin contestar se
  cierra** (`stopPoll`) al enviar el siguiente.
- Solo cuenta el voto del dueño del chat. **El voto es definitivo** (2026-10-04): la encuesta se
  envía con `allows_revoting=False`. El tratamiento de un voto retirado (`score = NULL`) se mantiene
  solo como defensa.
- La tabla se llama **`training_evaluation`** (singular) y **sobrevive a `/interview`** (FK con
  `ON DELETE SET NULL`).
- **Canal independiente**: tabla propia como cola y resultado y **contenedor propio `evaluation`**
  (nombre genérico por si se extiende). No se toca la cola `training_notifications`.
- **Política de reintentos configurable** para encuestas y recordatorios (`RetryPolicy`). Nombres sin
  jerga: `retry_delay_seconds` (espera inicial que se duplica), `retry_max_delay_seconds` (tope),
  `sending_timeout_seconds` (bloqueo mientras se envía; columna `locked_until`), `batch_size`.
- El aviso por interacción de los recordatorios **mantiene sus 5 minutos fijos**; solo toma
  `max_attempts` de la política.
- Variables nuevas en `.env.example` y en los `.env` de cada entorno. En el compose de tests,
  valores fijos en `environment:` (intervalo 10 s).
- `TRAINING_DUE_MESSAGE` se actualiza para aclarar que "avisos off" no afecta a las encuestas.
- `training_plans` y `training_mesocycles` **se mantienen separadas** (decidido).
- Documentación de la funcionalidad repartida en `trainer-agent.md` ("Fechas y avisos"),
  `entornos-y-despliegue.md` y `modelo-datos.md` (corregir también su diagrama, le faltan las tablas
  `training_*`).

---

## 2. Hecho

| Paso | Estado | Detalle |
|---|---|---|
| 1. Política de reintentos y settings | ✅ Aplicado y validado | `domain/retry_policy.py`, `_RetrySettings`, `TrainingSettings` (prefijo `training_reminder_`, alias y `populate_by_name`), `EvaluationSettings`; renombrados en `webhook.py` y `training_reminders.py`. 43 tests, ruff y mypy en verde |
| `.env.example` | ✅ | Variables `training_reminder_*` nuevas y `evaluation_*` |
| 2. Migraciones y modelos | ✅ Aplicado y revisado (outbox) | Sin `plan_version`, `goal` nullable, índice parcial `ix_training_evaluation_due`, migración `e5c7a9b1d3f4` (programa las semanas futuras de los ciclos abiertos). Tests IT de migración actualizados, sin ejecutar |
| Backfill de `goal` | ✅ | Se hace con Alembic; instrucciones en [backfill-training-plan-goal.md](backfill-training-plan-goal.md) |
| 3. Repositorio | ✅ Aplicado (outbox) | `upcoming_polls` en dominio; `schedule_evaluations` / `cancel_pending_evaluations` llamados desde `save_training_plan`, `accept` (renovación), `set_start`, `close_cycle` y `restart_interview`; `claim` copia `goal`/`plan_id` y cancela semanas superadas; se elimina `enqueue_due`. Tests unitarios e IT reescritos, sin ejecutar |
| 4. Helper de envío | ✅ Aplicado | `jobs/telegram_delivery.py` (`classify_failure`); el worker de recordatorios usa `RetryPolicy` (`batch_size`, `sending_timeout` en `claim_reminder`, espera de la política). El aviso por interacción no cambia (ya cumplía: 5 min fijos y `max_attempts`; está en la capa de servicio y no debe depender de `infrastructure`). Tests escritos, sin ejecutar |
| 5 + 7. Worker `evaluation` y textos | ✅ Aplicado | `jobs/worker_loop.py` (`run_periodically`, bucle común de los dos workers); `jobs/evaluation.py` (`sendPoll` no anónimo, cierre *best effort* del poll anterior con `stopPoll`, `classify_failure`); textos `EVALUATION_POLL_*` y `TRAINING_DUE_MESSAGE` en `constants.py`. Tests escritos, sin ejecutar |
| 6. Webhook `poll_answer` | ✅ Aplicado | `"poll_answer"` en `allowed_updates` (`main.py`); `ConversationService` recibe `EvaluationRepository` y procesa el voto antes del enrutado de comandos, sin contestar. Tests en `test_poll_answer.py` |
| 8. Composes | ✅ Aplicado | `evaluation-dev`, `evaluation` (local), `evaluation-prod`; en tests, perfil `evaluation` con intervalo 10 s (como `reminders`, `make tests` no lo levanta) |
| 10. Flujo completo | ✅ Escrito | Stub server con `sendPoll`/`stopPoll` y `GET /__polls`; `tests/it/test_evaluation_flow.py` ejecuta el worker en proceso contra el stub y vota por el webhook. Sin ejecutar |
| 11. Documentación | ✅ | `trainer-agent.md`, `entornos-y-despliegue.md`, `modelo-datos.md` (diagrama con tablas `training_*`), `how-to.md`, README y AGENTS.md |

---

## 3. Decisiones tomadas (2026-10-04)

1. **Datos de `training_evaluation`**: FK (`ON DELETE SET NULL`) + copia mínima de `goal`;
   se elimina `plan_version`.
2. **Programación outbox**: las 4 encuestas se insertan **al nacer el ciclo con fecha**, en la misma
   transacción: `save_training_plan` (primer plan), `accept()` con `kind == "renewal"` y
   `set_start()`. Los ajustes del mismo ciclo y `postpone` no programan nada.
   - `close_cycle` cancela las encuestas pendientes del ciclo (renovación o cierre anticipado).
   - Al reclamar se cancela si `due_week(started_at, now)` es mayor que la semana de la fila
     (semana superada tras una caída), o si el ciclo está cerrado o ya no es el vigente.
   - `goal` y `plan_id` se toman **al enviar** (nullable hasta entonces).
   - Índice parcial `(due_at) WHERE state IN ('pending', 'sending')`: el tick cuesta O(vencidas),
     no O(ciclos abiertos).
   - Descartado encadenar (programar solo la siguiente semana): oculta el calendario y pierde las
     filas `cancelled` que sirven para la tasa de respuesta.
3. **Ciclos ya abiertos al desplegar**: una migración de datos programa **solo las semanas
   futuras** (`due_at > now()`), para que nadie reciba de golpe encuestas de semanas ya pasadas.
4. **Migraciones sin aplicar** en ninguna base (ni esquema ni backfill de `goal`): se editan
   directamente y se aplican cuando el desarrollo esté terminado.

---

## 4. Pendiente

| Qué | Detalle |
|---|---|
| Verificación | `make tests` en local (unitarios + IT con cobertura ≥ 80 %), `ruff`, `mypy`. Nada de lo escrito desde el paso 2 se ha ejecutado |
| Pruebas manuales | Tabla de la sección 4 de [evaluation-tests.md](evaluation-tests.md) |
| Aplicar migraciones | `c2d8e4f6a1b3` → `d9a1b3c5e7f2` → `e5c7a9b1d3f4` (las aplica el `alembic upgrade head` del contenedor) |
| 9. Panel de Grafana | Hecho en parte (N4 de `fitcoach-business`): satisfacción media por cliente, % sin contestar, % no generadas y detalle por `chat_id`. Pendientes: media semanal y distribución 0-5 |

---

## 5. A tener en cuenta

- **`.venv` local sin `pgvector`**: la suite unitaria completa falla al importar. Sincronizar con
  `uv sync` (o `pip install -r src/requirements.txt`).
- **Tests de integración sin ejecutar**: necesitan Docker (`make tests`).
- **Variables para los `.env` reales** (las añade el desarrollador al terminar): `evaluation_enabled`
  y el resto de `evaluation_*`; opcionales las `training_reminder_*` nuevas.
- Desplegar la migración de `goal` junto con el paso 3 para que no haya planes nuevos sin `goal`.
