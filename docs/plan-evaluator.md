# Evaluador determinista de planes del entrenador

El módulo [`plan_evaluator.py`](../src/fitcoach/service/agent/plan_evaluator.py) revisa un plan
generado por el agente entrenador y lo compara con el perfil del cliente, el catálogo recuperado
y unas reglas fijas de calidad. No llama al LLM, no modifica el plan y no intenta repararlo:
devuelve hallazgos y métricas para explicar qué cumple el plan y qué conviene revisar.

Complementa la [documentación del agente entrenador](trainer-agent.md). Su uso actual está en las
devtools de depuración y comparación; **no es un filtro de aprobación de los planes que se envían
en el flujo de producción**.

## 1. Qué comprueba cada capa

| Capa | Responsabilidad |
| --- | --- |
| `domain/trainer_plan.py` | Pydantic valida tipos, límites de campos, cuatro semanas ordenadas, intensidades del mesociclo, número de días y coherencia del turno. |
| `TrainerChain` | Valida la respuesta del LLM y comprueba que los identificadores usados pertenecen al catálogo recuperado. Puede solicitar una reparación si la respuesta no valida. |
| `plan_evaluator.py` | Revisa reglas adicionales: coherencia con el perfil, nombres del catálogo, tiempo, volumen, progresión, RPE, cobertura muscular, lesiones, banderas rojas y longitud de mensajes. |

Un JSON válido puede tener una sesión demasiado larga o una descarga mal planteada. Esos son
problemas que el evaluador permite detectar después de la validación estructural.

El evaluador recibe objetos ya validados, no texto JSON arbitrario. Sus comprobaciones añaden
hallazgos en lugar de lanzar excepciones por incumplimientos; eso no sustituye la validación de
entrada ni garantiza que cualquier objeto construido saltándose Pydantic sea evaluable.

## 2. Entradas y puntos de entrada

Las entradas son:

- `TrainingPlan` o `TrainerTurn`: el plan estructurado, o el turno que incluye `reply` y `report`.
- `InterviewerProfile`: objetivo, entorno, disponibilidad, volumen tolerable, lesiones y banderas.
- `Sequence[Exercise]`: el catálogo exacto disponible para esa generación.

### `evaluate_plan(plan, profile, catalogue, evaluation=None)`

Evalúa el catálogo y el plan, calcula sus métricas y devuelve un `PlanEvaluation`. El argumento
opcional `evaluation` permite acumular hallazgos en un resultado existente.

Las comprobaciones se ejecutan en este orden:

```text
Catálogo
  → coherencia con el perfil
  → identificadores y nombres
  → duración y duplicados por sesión
  → volumen por músculo
  → progresión y descarga
  → límites de RPE
  → repeticiones y descansos por objetivo
  → continuidad de ejercicios
  → cobertura muscular
  → lesiones
  → banderas rojas
  → métricas del plan
```

### `evaluate_turn(turn, profile, catalogue)`

Es el punto de entrada usado por las devtools. Añade las comprobaciones que necesitan el turno
completo:

1. Revisa la longitud de `reply` y `report`.
2. Si no hay plan, evalúa el catálogo, añade el error `no_plan` y termina.
3. Si hay plan, llama a `evaluate_plan`.
4. Comprueba que se menciona una derivación profesional cuando existen banderas rojas.

Por tanto, llamar solo a `evaluate_plan` no comprueba la longitud de los mensajes ni la derivación
en el texto del turno. Un turno `answer`, válido para responder dudas, recibe `no_plan` aquí porque
este evaluador está orientado a evaluar generaciones de planes.

## 3. Resultado, severidades y puntuación

Cada `Finding` contiene:

| Campo | Significado |
| --- | --- |
| `rule` | Identificador estable de la regla, por ejemplo `session_over_budget`. |
| `severity` | `error`, `warning` o `info`. |
| `message` | Explicación del hallazgo con los valores que lo motivan. |
| `where` | Ubicación opcional: `W1` indica semana 1; `W2D3`, semana 2 y día 3. Puede estar vacía. |

`PlanEvaluation` agrupa `findings` y `metrics`. Expone `errors`, `warnings`, `passed`, `score` y
`to_dict()` para serializar el resultado.

| Severidad | Interpretación | Penalización por hallazgo |
| --- | --- | --- |
| `error` | Incumplimiento de una regla que el evaluador considera obligatoria. | 15 puntos |
| `warning` | Desviación o heurística que requiere revisión. | 3 puntos |
| `info` | Información sobre limitaciones del catálogo o cobertura no disponible. | Ninguna |

```text
score = max(0, 100 - 15 × errors - 3 × warnings)
passed = (errors == 0)
```

Se cuentan **hallazgos**, no tipos distintos de regla: una misma regla puede penalizar varias
veces si aparece en diferentes sesiones o semanas. La puntuación no es un porcentaje de seguridad
ni una probabilidad de que el plan sea correcto.

Por ejemplo, tres avisos y ningún error producen `score=91` y `passed=true`. Un error y ningún
aviso producen `score=85`, pero `passed=false`: no existe un umbral de puntuación para aprobar.

## 4. Reglas implementadas

### Perfil, catálogo y sesiones

| Regla | Severidad | Condición |
| --- | --- | --- |
| `profile_mismatch` | Error | `goal`, `environment` o `days_per_week` no coincide con el perfil. Puede haber un hallazgo por campo. |
| `unknown_exercise_id` | Error | Un ejercicio del plan no existe en el catálogo. |
| `name_mismatch` | Error | El nombre no coincide con el del identificador en el catálogo, ignorando mayúsculas y espacios en los extremos. |
| `session_over_budget` | Error | `estimated_minutes` supera `minutes_per_session`. |
| `session_time_formula_over_budget` | Aviso | La duración calculada supera el presupuesto de sesión en más de un 15 %. |
| `duplicate_exercise_in_day` | Error | Un mismo identificador aparece varias veces en una sesión. |

La estimación alternativa de tiempo usa:

```text
minutos = 8 + Σ[series × (40 + descanso_en_segundos)] / 60 + 5
```

Incluye 8 minutos de calentamiento, 40 segundos de trabajo por serie y 5 minutos de vuelta a la
calma. Cuenta el descanso por cada serie. Es una aproximación, no un cronometraje real; por eso su
incumplimiento es un aviso y admite la tolerancia del 15 %.

### Volumen, periodización y esfuerzo

| Regla | Severidad | Condición |
| --- | --- | --- |
| `volume_over_ceiling` | Error | Las series semanales para un `target` superan `tolerable_volume_sets`. Se revisa la semana 1; con banderas rojas, todas las semanas. |
| `no_progression` | Aviso | De S1 a S2 o de S2 a S3 disminuyen las series, o se mantienen sin aumentar el RPE medio. |
| `deload_volume` | Error | Las series totales de S4 son iguales o superiores a las de S1. |
| `deload_volume` | Aviso | S4 tiene menos series que S1, pero su proporción queda fuera del intervalo inclusivo 40–70 %. |
| `rpe_over_cap` | Error | Algún RPE supera 8 en S1, 9 en S3 o 6 en S4. No hay límite específico para S2 en esta regla. |

El volumen se suma por el `target` principal del ejercicio en el catálogo, no por todos los músculos
que participan en el movimiento. Si el identificador o su `target` no están disponibles, las series
se acumulan en `unknown`. Este conteo no pondera el trabajo indirecto de ejercicios compuestos.

El RPE medio es la media simple de los RPE presentes, sin ponderar por series. Los valores `None`
se omiten. La progresión no analiza carga, tempo ni dificultad técnica: puede advertir
`no_progression` aunque haya progresión real por una variable que no mide.

**Detalle importante de la descarga:** el mensaje del hallazgo dice «expected 50-60%», pero el
intervalo aceptado por `DELOAD_RANGE` es **40–70 %**. Para interpretar el resultado, manda el
intervalo implementado.

### Repeticiones, descansos y continuidad

Estas comprobaciones de rangos se aplican solo a la semana 1:

| Objetivo | Repeticiones aceptadas | Descanso aceptado |
| --- | --- | --- |
| `lose_fat` | 8–20 | 30–90 segundos |
| `gain_muscle` | 5–15 | 60–240 segundos |
| `performance` | 1–10 | 90–300 segundos |

`reps_outside_goal_range` es un aviso cuando el rango numérico del ejercicio no se solapa con el
aceptado. No exige que todo el rango quede dentro: por ejemplo, `4-6` se solapa con `5-15`.
Las prescripciones por tiempo, como `30 s`, y los textos sin números no se evalúan por esta regla.
`rest_outside_goal_range` avisa de descansos fuera del intervalo inclusivo correspondiente.
Los ejercicios fuera de rango se agrupan en un hallazgo de repeticiones y otro de descansos.

`exercises_change_between_weeks` avisa cuando un día de S2 o S3 conserva menos del 50 % de los
identificadores del mismo día de S1. Compara con S1, no con la semana inmediatamente anterior,
y no exige continuidad en S4.

### Cobertura muscular

El catálogo agrupa los `target` conocidos en pecho, espalda, piernas, hombros, brazos, core y
cardio. La cobertura del plan se revisa en la semana 1 para tres grupos esenciales:
`chest`, `back` y `legs`.

| Regla | Severidad | Condición |
| --- | --- | --- |
| `catalogue_missing_group` | Información | El catálogo carece de alguno de los siete grupos reconocidos. |
| `group_not_trained` | Aviso | S1 no incluye un grupo esencial, aunque el catálogo sí ofrece ejercicios de ese grupo. |
| `group_not_trained` | Información | S1 no incluye un grupo esencial y el catálogo tampoco lo ofrece. |

Esta distinción ayuda a separar problemas del prompt de problemas de recuperación. Un grupo
ausente en el catálogo no reduce la puntuación. La regla no determina si omitir un grupo es
clínicamente apropiado por una lesión.

### Lesiones y banderas rojas

| Regla | Severidad | Condición |
| --- | --- | --- |
| `injury_not_recorded` | Error | El perfil tiene lesiones, pero `excluded_by_injury` está vacío. |
| `phantom_injury_exclusion` | Aviso | Hay exclusiones por lesión, pero el perfil no registra lesiones. |
| `possible_injury_conflict` | Aviso | Palabras de la lesión activan patrones que aparecen en nombres de ejercicios. |
| `red_flags_maximal_effort` | Error | Hay banderas rojas y algún ejercicio tiene RPE ≥ 9. |
| `red_flags_no_referral` | Error | Hay banderas rojas y ni `report` ni `reply` contienen alguna palabra de derivación reconocida. |

Los patrones de lesión cubren rodilla, hombro, zona lumbar y muñeca. Buscan fragmentos de texto en
`location`, `type` y `restriction`, y después en los nombres de los ejercicios; no interpretan
semánticamente las notas, la técnica ni las adaptaciones.

La derivación también se detecta por palabras clave, como `profesional`, `doctor` o
`fisioterapeut`. No verifica que se haya redactado una recomendación adecuada ni distingue una
mención afirmativa de una negación. Estas heurísticas pueden producir falsos positivos o negativos:
**el evaluador no sustituye una revisión profesional ni certifica la seguridad clínica del plan**.

### Mensajes y ausencia de plan

| Regla | Severidad | Condición |
| --- | --- | --- |
| `reply_too_long` | Aviso | `reply` supera 600 caracteres. |
| `report_over_telegram_limit` | Error | `report`, si existe, supera 4096 caracteres. |
| `no_plan` | Error | El turno evaluado no contiene un plan. |

Los límites usan `len()` sobre el texto; no calculan el tamaño de una representación final con
formato Telegram. Estas reglas pertenecen a `evaluate_turn`, no a `evaluate_plan`.

## 5. Métricas disponibles

| Métrica | Contenido |
| --- | --- |
| `catalogue_size` | Número de ejercicios recibidos en el catálogo. |
| `catalogue_groups` | Número de ejercicios por grupo muscular reconocido en el catálogo. |
| `weekly_sets` | Series totales de cada una de las cuatro semanas, en orden. |
| `mean_rpe` | RPE medio por semana, redondeado a dos decimales; `None` si no hay valores. |
| `week1_sets_per_target` | Series de S1 agrupadas por músculo `target`. |
| `tolerable_volume_sets` | Techo de volumen tomado del perfil. |
| `max_estimated_minutes` | Mayor duración declarada de una sesión del plan. |
| `max_formula_minutes` | Mayor duración calculada por la fórmula, redondeada. |
| `minutes_per_session` | Presupuesto de tiempo del perfil. |
| `exercises_per_day` | Media de ejercicios por sesión de todo el plan, con un decimal. |
| `distinct_exercises` | Número de identificadores diferentes usados en todo el plan. |

Si el turno no tiene plan, solo se calculan las métricas del catálogo. Las métricas complementan la
puntuación: permiten saber si un cambio mejora la duración, el volumen o la variedad, aunque dos
variantes obtengan el mismo `score`.

## 6. Uso desde las devtools

Después de una generación validada, `trainer_runner.run_trainer_case` llama a `evaluate_turn`.
`trainer-debug` muestra la puntuación y los hallazgos no informativos; los artefactos conservan
también los informativos:

| Archivo | Contenido |
| --- | --- |
| `evaluation.json` | Resultado serializado con hallazgos, métricas, puntuación y aprobación. |
| `evaluation.md` | Informe legible, agrupado por severidad. |
| `run.json` | Resumen con `score`, `eval_errors` y `eval_warnings`, además de los datos de generación. |

`trainer-compare` usa esos resultados para comparar casos, skills y modelos. Una puntuación baja
no hace fallar por sí sola una generación: `trainer-debug` devuelve 0 si produjo un plan,
independientemente de sus hallazgos; la comparación devuelve 1 si alguna ejecución terminó con
estado `error`.

### Volver a evaluar sin llamar al modelo

```bash
make trainer-debug ARGS="--evaluate-run runs/trainer/<carpeta-de-ejecucion>"
```

El comando lee `plan.json`, `profile.json` y `catalogue.json` de la ejecución guardada y vuelve a
escribir `evaluation.json` y `evaluation.md`. No regenera el plan, no consume tokens del LLM y no
actualiza el resumen histórico de `run.json`.

En este modo, el código de salida depende del evaluador: 0 si no hay errores y 1 si los hay. Los
avisos por sí solos no hacen fallar el comando. El target de Makefile sigue requiriendo resolver
el fichero de entorno de desarrollo, aunque la reevaluación no necesite llamar a servicios.

## 7. Cómo ampliar el evaluador

Las reglas actuales son código Python y constantes; no se cargan automáticamente desde
`SKILL.md`. Al cambiar una regla de la skill, hay que revisar si corresponde actualizar también
el evaluador.

Para añadir una comprobación del plan, seguir el patrón de las funciones `_check_*`, añadir sus
hallazgos con `_add` e incorporarla a `checks` en `evaluate_plan`. Si necesita `reply` o `report`,
conectarla desde `evaluate_turn`. Elegir una severidad acorde con la certeza de la comprobación,
no solo con la importancia del tema.

Los tests están en
[`tests/unit_test/test_plan_evaluator.py`](../tests/unit_test/test_plan_evaluator.py).
Cubren planes correctos, reglas que se activan, métricas y serialización. Una nueva regla debería
incluir tanto el caso que incumple como el que cumple y los límites relevantes del umbral.
