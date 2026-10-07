# Plan de pruebas: encuestas de satisfacción (`evaluation`)

> **Histórico.** Los tests de los workers (`test_training_reminders.py`, `test_evaluation_worker.py`, `test_worker_loop.py`) se sustituyeron por `test_scheduler.py` y los IT de `test_evaluation_flow.py`, `test_evaluation_repository.py`, `test_cycle_jobs.py` y `test_job_repository.py`.

Lista de verificación de la funcionalidad de encuestas semanales: qué tests automáticos existen, qué
cubren y qué hay que probar a mano en Telegram. Se completa a medida que avanza el desarrollo.

Estado: ✅ escrito y ejecutado · 🟡 escrito, pendiente de ejecutar · ⬜ pendiente de escribir.

---

## 1. Cómo ejecutarlos

| Qué | Comando | Requisitos |
|---|---|---|
| Unitarios de un fichero | `.venv/Scripts/python.exe -m pytest tests/unit_test/<fichero> --no-cov -q` | `.venv` sincronizado (`uv sync`; hoy falta `pgvector` en local) |
| Suite completa (unit + IT, cobertura ≥ 80 %) | `make tests` | Docker: levanta `tests/docker-compose-test.yml` |
| Lint y tipos | `ruff check .`, `ruff format --check .`, `mypy src/` | `.venv` |

---

## 2. Tests unitarios

### 2.1 Política de reintentos — `tests/unit_test/test_retry_policy.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| ✅ | `test_delay_doubles_with_each_attempt` | OK | La espera se duplica: 60 s tras el intento 1, 120 s tras el 2 |
| ✅ | `test_delay_never_exceeds_the_maximum` | KO | Por muchos intentos, la espera no pasa del tope |
| ✅ | `test_is_exhausted_when_attempts_reach_the_maximum` | KO | Con 5 intentos de 5, no se reintenta más |
| ✅ | `test_is_not_exhausted_below_the_maximum` | OK | Con 4 de 5, se sigue reintentando |

### 2.2 Configuración — `tests/unit_test/test_settings.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| ✅ | `TestTrainingSettings::test_defaults_reproduce_the_previous_hardcoded_policy` | OK | Sin configurar nada, los recordatorios se comportan como antes (30 s, 3600 s, 120 s, 100) |
| ✅ | `TestTrainingSettings::test_keeps_reading_the_existing_variable_names` | OK | Las variables de los `.env` actuales siguen funcionando |
| ✅ | `TestTrainingSettings::test_reads_the_new_retry_variables` | OK | Se leen las variables nuevas de reintentos |
| ✅ | `TestTrainingSettings::test_reminders_are_disabled_without_configuration` | OK | Los recordatorios no se activan por accidente |
| ✅ | `TestEvaluationSettings::test_is_disabled_without_configuration` | OK | Las encuestas no se activan por accidente |
| ✅ | `TestEvaluationSettings::test_reads_the_retry_policy_from_the_environment` | OK | La política de las encuestas es configurable |
| ✅ | `TestEvaluationSettings::test_rejects_a_max_delay_below_the_initial_delay` | KO | Un tope menor que la espera inicial aborta el arranque |
| ✅ | `TestEvaluationSettings::test_rejects_out_of_range_values` | KO | Intervalo < 10 s, 0 intentos, bloqueo < 10 s o lote 0 abortan el arranque |

### 2.3 Worker de recordatorios — `tests/unit_test/test_training_reminders.py` (existente)

| Estado | Qué comprueba |
|---|---|
| ✅ | Sigue en verde tras extraer la política de reintentos (paso 1) |
| 🟡 | `test_claim_uses_the_configured_sending_timeout`: el bloqueo usa `sending_timeout_seconds` (OK) |
| 🟡 | `test_batch_stops_at_the_configured_size`: un lote no pasa de `batch_size` (KO) |
| 🟡 | `test_network_error_is_retried_with_the_configured_delay`: error de red → espera `retry_delay × 2^intentos` (OK) |
| 🟡 | `test_rate_limit_waits_what_telegram_asks`: `RetryAfter` → espera lo que pide Telegram (OK) |
| 🟡 | `test_exhausted_delivery_after_an_interruption_is_not_sent`: intentos agotados tras una caída → `failed` sin enviar (KO) |
| 🟡 | `test_unexpected_telegram_error_is_recorded_and_propagated`: error desconocido → `failed` y el worker se detiene (KO) |
| — | El aviso por interacción no cambia: ya tenía 5 minutos fijos y `max_attempts` configurable (cubierto por los tests de `training_service`) |

### 2.3 bis Clasificación de fallos de Telegram — `tests/unit_test/test_telegram_delivery.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| 🟡 | `TestRateLimit::test_waits_what_telegram_asks` | OK | `RetryAfter(5)` → reintento en 5 s |
| 🟡 | `TestRateLimit::test_waits_at_least_one_second` | KO | `RetryAfter(0)` → al menos 1 s |
| 🟡 | `TestRateLimit::test_fails_once_attempts_are_exhausted` | KO | Con los intentos agotados → `failed` |
| 🟡 | `TestTransientFailure::test_retries_with_the_policy_delay` | OK | `NetworkError`/`TimedOut` → espera de la política (60 s en el intento 1) |
| 🟡 | `TestTransientFailure::test_the_delay_is_capped` | KO | La espera no supera `retry_max_delay` |
| 🟡 | `TestTransientFailure::test_fails_once_attempts_are_exhausted` | KO | Con los intentos agotados → `failed` |
| 🟡 | `TestPermanentFailure::test_fails_without_retry` | KO | `BadRequest`/`Forbidden` → `failed` sin reintento |
| 🟡 | `TestPermanentFailure::test_an_unknown_telegram_error_fails_and_is_flagged` | KO | Error desconocido → `failed` y marcado como inesperado |

### 2.3 ter Repositorio de recordatorios — `tests/it/test_training_repository.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| 🟡 | `test_claimed_reminder_stays_locked_for_the_sending_timeout` | OK/KO | `lease_until = now + sending_timeout`; no se puede volver a reclamar antes y sí después |

### 2.4 Calendario y escala — `tests/unit_test/test_training_evaluation.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| 🟡 | `TestDueWeek::test_no_poll_is_due_before_the_first_week_ends` | KO | A los 6 días y 23 h no toca ninguna encuesta |
| 🟡 | `TestDueWeek::test_first_week_is_due_after_seven_days` | OK | A los 7 días toca la semana 1 |
| 🟡 | `TestDueWeek::test_returns_only_the_most_recent_due_week` | OK | A los 22 días toca solo la 3, no la 1 ni la 2 |
| 🟡 | `TestDueWeek::test_never_goes_beyond_the_last_week_of_the_mesocycle` | KO | Pasadas las 4 semanas no hay semana 5 |
| 🟡 | `TestDueWeek::test_rejects_naive_dates` | KO | Fechas sin zona horaria se rechazan |
| 🟡 | `TestDueAt::test_each_week_is_due_seven_days_after_the_previous` | OK | Semana 1 a los 7 días, semana 4 a los 28 |
| 🟡 | `TestUpcomingPolls::test_a_cycle_starting_now_schedules_its_four_weeks` | OK | Ciclo que empieza ahora: semanas 1-4 a los 7, 14, 21 y 28 días |
| 🟡 | `TestUpcomingPolls::test_a_cycle_starting_in_the_future_schedules_its_four_weeks` | OK | Renovación con fecha futura: las 4 semanas |
| 🟡 | `TestUpcomingPolls::test_weeks_already_past_are_skipped` | KO | Ciclo empezado hace 10 días: solo 2, 3 y 4 |
| 🟡 | `TestUpcomingPolls::test_a_week_due_exactly_now_is_skipped` | KO | Una semana que vence justo ahora ya no se programa |
| 🟡 | `TestUpcomingPolls::test_nothing_is_scheduled_once_the_mesocycle_is_over` | KO | Pasados 28 días no se programa nada |
| 🟡 | `TestUpcomingPolls::test_rejects_naive_dates` | KO | Fechas sin zona horaria se rechazan |
| 🟡 | `TestScoreFromOption::test_the_option_index_is_the_score` | OK | La opción elegida (0, 3, 5) es la nota |
| 🟡 | `TestScoreFromOption::test_a_retracted_vote_has_no_score` | OK | Voto retirado: sin nota |
| 🟡 | `TestScoreFromOption::test_rejects_an_option_outside_the_scale` | KO | `-1` y `6` se rechazan |

### 2.5 Pendientes de escribir

| Estado | Área | Casos previstos |
|---|---|---|
| 🟡 | Webhook `poll_answer` — `tests/unit_test/test_poll_answer.py` | Voto guardado con nota y votante (OK); voto retirado → `None` (OK); el bot no contesta (OK); `poll_id` desconocido sin error (KO); opción fuera de escala no se guarda (KO); votante anónimo ignorado (KO); sin repositorio de evaluaciones se ignora (KO); update reenviado no se guarda dos veces (KO); un fallo de base no escapa del webhook (KO) |

### 2.6 Worker de encuestas — `tests/unit_test/test_evaluation_worker.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| 🟡 | `TestPollTexts::test_the_question_names_the_week_and_the_goal` | OK | "Semana 2 de tu plan para ganar músculo: …" |
| 🟡 | `TestPollTexts::test_without_a_known_goal_the_question_stays_generic` | KO | Sin `goal` o con uno desconocido: pregunta sin objetivo |
| 🟡 | `TestPollTexts::test_there_is_one_option_per_score` | OK | 6 opciones numeradas de 0 a 5 con los textos acordados |
| 🟡 | `test_disabled_worker_does_not_claim` | KO | Histórico: con `scheduler_enabled=false` la app no arranca la tarea (cubierto en `test_main.py`) |
| 🟡 | `test_sends_a_non_anonymous_poll_to_the_cycle_thread` | OK | `sendPoll` al chat e hilo del ciclo, no anónimo, una respuesta y sin poder cambiar el voto (`allows_revoting=False`); guarda `poll_id` y `message_id` |
| 🟡 | `test_closes_the_previous_unanswered_poll_before_sending` | OK | `stopPoll` del anterior y después `sendPoll` |
| 🟡 | `test_nothing_is_closed_without_a_previous_unanswered_poll` | KO | Sin anterior pendiente no se llama a `stopPoll` |
| 🟡 | `test_failing_to_close_the_previous_poll_does_not_block_the_new_one` | KO | Si `stopPoll` falla, la nueva encuesta se envía igual |
| 🟡 | `test_claim_uses_the_configured_sending_timeout` | OK | El bloqueo usa `evaluation_sending_timeout_seconds` |
| 🟡 | `test_batch_stops_at_the_configured_size` | KO | Un lote no pasa de `evaluation_batch_size` |
| 🟡 | `test_rate_limit_reschedules_the_poll` | KO | `RetryAfter` → reintento cuando pide Telegram |
| 🟡 | `test_a_blocked_bot_marks_the_poll_failed` | KO | `Forbidden` → `failed`, sin detener el worker |
| 🟡 | `test_exhausted_delivery_after_an_interruption_is_not_sent` | KO | Intentos agotados tras una caída → `failed` sin enviar |
| 🟡 | `test_unexpected_telegram_error_is_recorded_and_propagated` | KO | Error desconocido → `failed` y el worker se detiene |
| 🟡 | `test_a_lock_lost_after_sending_is_propagated` | KO | Enviada pero con el bloqueo caducado → error visible |

### 2.7 Bucle común de los workers — `tests/unit_test/test_worker_loop.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| 🟡 | `test_once_runs_a_single_batch_and_releases_resources` | OK | `--once`: un lote con su sesión y bot; cierra bot y base |
| 🟡 | `test_once_propagates_database_errors_and_still_releases_resources` | KO | `--once` con la base caída: falla, pero libera recursos |
| 🟡 | `test_periodic_mode_survives_database_errors` | KO | En modo periódico un error de base no detiene el worker |

---

## 3. Tests de integración

### 3.1 Migración — `tests/it/test_evaluation_migration.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| 🟡 | `test_backfills_the_goal_of_existing_plans` | OK | Los planes anteriores a la migración reciben su `goal` |
| 🟡 | `test_schedules_only_the_future_weeks_of_open_cycles` | OK | Ciclo abierto hace 10 días: se programan las semanas 2, 3 y 4, ninguna ya vencida |
| 🟡 | `test_does_not_schedule_cycles_without_future_weeks` | KO | Ciclo cerrado, sin fecha o con las 4 semanas pasadas: nada programado |
| 🟡 | `test_does_not_schedule_a_cycle_that_is_no_longer_current` | KO | Un ciclo abierto que no es el vigente del chat no se programa |
| 🟡 | `test_evaluation_survives_the_deletion_of_its_plan_and_cycle` | OK | Tras un `/interview` (borrado de plan y ciclo) la evaluación conserva `score` y `goal` |
| 🟡 | `test_rejects_a_score_outside_zero_to_five` | KO | `-1` y `6` se rechazan |
| 🟡 | `test_rejects_a_week_outside_the_mesocycle` | KO | Semana `0` y `5` se rechazan |
| 🟡 | `test_rejects_two_evaluations_for_the_same_cycle_week` | KO | La misma semana no se encola dos veces |
| 🟡 | `test_downgrade_removes_the_evaluation_schema` | OK | El downgrade deja el esquema como estaba |
| 🟡 | `tests/it/test_training_migration.py` (existente) | OK | Su downgrade atraviesa también las migraciones nuevas |

### 3.2 Repositorio — `tests/it/test_evaluation_repository.py`

| Estado | Test | Caso | Qué comprueba |
|---|---|---|---|
| 🟡 | `test_saving_a_plan_copies_its_goal` | OK | Un plan nuevo guarda `goal` |
| 🟡 | `test_the_first_plan_schedules_four_weekly_polls` | OK | El primer plan programa las semanas 1-4 a los 7/14/21/28 días, sin `goal` ni `plan_id` todavía |
| 🟡 | `test_a_plan_change_within_the_cycle_schedules_nothing_new` | KO | Un cambio de ejercicios en el mismo ciclo no toca las encuestas |
| 🟡 | `test_renewal_cancels_the_old_cycle_and_schedules_the_new_one` | OK | Renovación: las del ciclo viejo quedan `cancelled` y el nuevo programa 4 desde su fecha de inicio |
| 🟡 | `test_closing_the_cycle_early_cancels_only_its_pending_polls` | KO | Cierre anticipado: la semana ya enviada se conserva y el resto se cancela |
| 🟡 | `test_postponing_schedules_no_extra_poll` | KO | Aplazar no crea ni mueve encuestas |
| 🟡 | `test_a_legacy_cycle_receiving_a_start_schedules_only_its_future_weeks` | OK | `set_start` con fecha de hace 10 días programa solo las semanas 2-4 |
| 🟡 | `test_restarting_the_interview_cancels_pending_polls_but_keeps_them` | KO | `/interview`: las pendientes se cancelan, la enviada se conserva con su `goal` y todas quedan con `mesocycle_id` a `NULL` |
| 🟡 | `test_nothing_is_claimed_before_the_first_week_ends` | KO | Antes de 7 días no se reclama nada |
| 🟡 | `test_claim_locks_the_poll_and_copies_the_current_plan` | OK | Reclamar bloquea la fila, devuelve chat, hilo, semana y objetivo y copia `goal` y `plan_id` del plan vigente |
| 🟡 | `test_after_an_outage_only_the_latest_week_is_sent` | OK | Tras una caída (día 22) se envía solo la semana 3; la 1 y la 2 se cancelan |
| 🟡 | `test_disabled_reminders_do_not_stop_the_polls` | OK | `reminders_enabled=false` no impide las encuestas |
| 🟡 | `test_two_workers_never_claim_the_same_poll` | KO | Dos workers a la vez: solo uno la obtiene |
| 🟡 | `test_a_poll_whose_cycle_closed_is_cancelled_on_claim` | KO | Ciclo cerrado sin pasar por `close_cycle`: el `claim` la cancela (red de seguridad) |
| 🟡 | `test_claim_reports_the_previous_unanswered_poll_to_close` | OK | Al enviar la semana 2 se indica el poll sin contestar de la semana 1 para cerrarlo |
| 🟡 | `test_an_answered_previous_poll_is_not_reported_to_close` | KO | Si la semana 1 se contestó, no hay nada que cerrar |
| 🟡 | `test_mark_sent_stores_the_telegram_identifiers` | OK | Guarda `poll_id`, `message_id` y `sent_at` y libera el bloqueo |
| 🟡 | `test_finish_with_retry_reschedules_the_poll` | OK | Un reintento la reprograma y no se recoge antes de tiempo |
| 🟡 | `test_finish_as_failed_stops_retrying` | KO | Un fallo definitivo la marca `failed` |
| 🟡 | `test_a_worker_whose_lock_expired_cannot_finish_the_poll` | KO | Un worker cuyo bloqueo caducó no puede cerrarla |
| 🟡 | `test_the_owner_answer_is_stored` | OK | El voto del dueño guarda `score` y `answered_at` |
| 🟡 | `test_a_retracted_vote_clears_the_score` | OK | Voto retirado: `score` y `answered_at` a `NULL` |
| 🟡 | `test_an_answer_from_another_user_is_ignored` | KO | El voto de otro usuario no cuenta |
| 🟡 | `test_an_answer_to_an_unknown_poll_is_ignored` | KO | Un `poll_id` desconocido no falla |

### 3.3 Pendientes de escribir

| Estado | Área | Casos previstos |
|---|---|---|
| 🟡 | `tests/it/test_evaluation_flow.py::test_a_due_poll_is_sent_and_the_owner_vote_is_stored` (OK) | Plan guardado → semana 1 vencida → worker en proceso → `sendPoll` en el stub con la pregunta y el objetivo → `poll_answer` por el webhook → `score = 4` |
| 🟡 | `test_a_vote_from_another_user_is_not_stored` (KO) | El voto de otro usuario por el webhook no cambia `score` |
| 🟡 | `test_nothing_is_sent_before_the_first_week_ends` (KO) | Sin semanas vencidas el worker no envía nada |
| — | Compose de tests | El servicio `evaluation` (perfil `evaluation`) no lo levanta `make tests`; el flujo se prueba ejecutando el worker en proceso |

---

## 4. Pruebas manuales en Telegram (entorno dev)

Con `scheduler_enabled=true` y un intervalo corto en `.env.dev`. Para no esperar semanas, ajustar a
mano `training_mesocycles.started_at` hacia el pasado en la base de dev.

| Estado | Escenario | Resultado esperado |
|---|---|---|
| ⬜ | `started_at` hace 7 días | Llega el poll de la semana 1 con el objetivo del plan y opciones 0-5 |
| ⬜ | Votar una opción | `training_evaluation.score` guarda el valor; el bot no responde nada |
| ⬜ | Intentar cambiar o retirar el voto | Telegram no lo permite; `score` se mantiene |
| ⬜ | No contestar y pasar a la semana 2 | Se cierra el poll de la semana 1 y llega el de la semana 2 |
| ⬜ | Worker parado durante las semanas 2 y 3, después arrancado | Llega solo el poll de la semana 3; la 2 queda `cancelled` |
| ⬜ | `/train avisos off` | Las encuestas siguen llegando; el recordatorio de cierre no |
| ⬜ | `/train posponer` | No llega ninguna encuesta extra |
| ⬜ | Cerrar el ciclo antes de tiempo | No llegan más encuestas de ese ciclo |
| ⬜ | Día 28 | Llegan el poll de la semana 4 y el recordatorio de cierre, como mensajes independientes |
| ⬜ | `/interview` tras haber votado | La fila de `training_evaluation` sigue existiendo con `plan_id`/`mesocycle_id` a `NULL` |
| — | Panel de Grafana | Aplazado (backlog) |
