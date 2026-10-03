# Agente `trainer`

`trainer` es el Agente 2 de FitCoachIA. No entrevista: parte del perfil que el agente
[`interviewer`](interviewer-agent.md) dejó en `interviewer_profiles` para el `chat_id` de Telegram,
recupera ejercicios de la base de datos vectorial y diseña un mesociclo de 4 semanas. Después
responde a las preguntas del usuario sobre ese plan.

No diagnostica, prescribe ni sustituye a profesionales sanitarios. Respeta las lesiones declaradas
en el perfil y, ante señales de riesgo (`flags.red`), mantiene el plan conservador y recomienda
atención profesional.

## Flujo de una generación de plan

1. El usuario envía `/train` y Telegram entrega el update en `POST /webhook/response`.
2. `ConversationService` busca el perfil del `chat_id` en `interviewer_profiles`. Si no existe,
   responde que hace falta `/interview` y termina.
3. Avisa al usuario de que está generando el plan: la recuperación más la llamada al modelo tardan
   más que un turno normal de conversación.
4. `ExerciseRetriever` construye una consulta por grupo muscular, la vectoriza con el servicio
   `embedder` y busca en pgVector por distancia coseno.
5. `TrainerChain` compone el prompt de sistema con el catálogo recuperado en `{{rag_context}}`, le
   añade el perfil y hace **una** llamada al modelo.
6. Valida el JSON y, además, comprueba que **todos los `exercise_id` vienen del catálogo
   recuperado**. Si no cumple, solicita una única reparación.
7. Persiste y activa el primer plan antes de enviar el informe. Con un plan vigente,
   `/train` abre la revisión descrita más abajo, no regenera silenciosamente.

Los mensajes posteriores, mientras la sesión de entrenamiento está `active`, van al modo preguntas:
se consulta en PostgreSQL el plan apuntado por `training_sessions.current_plan_id`, el perfil efectivo y el historial propio del
agente. No se llama al embedder ni a pgVector.

Este modo utiliza `prompts/trainer/answer_prompt.txt`, sin la skill de generación ni el catálogo.
El plan guardado prevalece sobre el historial y el perfil aporta restricciones y contexto de
seguridad. Si falta información, el entrenador no debe inventarla. Las consultas son de solo lectura:
no sustituyen ejercicios, no ajustan el plan ni crean versiones. Una intención de renovación o
sustitución abre un flujo independiente; nunca autoriza por sí misma una modificación.
Durante una revisión abierta, `/train consulta PREGUNTA` permite consultar sin responder la revisión.

## Continuidad, revisión y confirmación

La interacción principal usa **botones inline**: «Empezar hoy», «Elegir fecha»,
«Cambiar un ejercicio» y «Descartar borrador». No hace falta escribir el identificador.
Elegir fecha ofrece mañana, próximo lunes u otra fecha; solo esta última pide escribir
`AAAA-MM-DD`. Para una sustitución se muestra «Aplicar cambio» y cada alternativa
se puede seleccionar con su propio botón. El cierre ofrece «Terminé y todo bien»,
«Terminé, pero quiero ajustar algo» o «Todavía no (recordar en 7 días)».
Los comandos siguientes siguen como alternativa.

El borrador se presenta en una sola tarjeta compacta con objetivo, frecuencia,
duración máxima de las sesiones, ejercicios de la primera semana y progresión de
series/RPE del bloque. Se construye desde el plan validado, no desde un nuevo resumen
del modelo. Las restricciones y alertas siguen visibles antes de aceptar.
«Ver plan completo y detalles» despliega todas las semanas, descansos, notas, informe,
revisión interpretada y perfil efectivo; termina con la tarjeta y los botones de decisión.
Consultar detalles no cambia el borrador ni consume una llamada al LLM.

El webhook admite `callback_query` y responde inmediatamente a las pulsaciones.
Cada botón lleva el id y revisión del flujo; las acciones comprueban el chat propietario
y rechazan controles obsoletos. La aceptación verifica también la revisión dentro de
la transacción. Los botones consumidos se retiran del mensaje original.
Las confirmaciones por botón están limitadas a chats privados del propietario; no
se admite que otra persona confirme una propuesta desde un grupo o un mensaje reenviado.

El ciclo dura cuatro semanas desde el inicio confirmado, no desde la creación del borrador.
Al alcanzar la fecha prevista, el bot propone revisar el bloque sin asumir que se realizaron
las sesiones. También se puede declarar su finalización antes. No hay diario de ejecución:
el cierre y los resultados son autodeclarados, y lo desconocido sigue siendo desconocido.

`/train` con plan vigente ofrece un cierre rápido. «Terminé y todo bien» confirma el
cierre y genera directamente un borrador conservando el perfil y las restricciones,
sin inventar adherencia, mejoras ni cargas. Este botón confirma ausencia de molestias
nuevas y de cambios de objetivo, horarios y material; no llama al extractor de revisión.
«Terminé, pero quiero ajustar algo» confirma el cierre y abre una sola pregunta libre.
El extractor organiza la respuesta en adherencia, resultados, recuperación, molestias,
preferencias y cambios, manteniendo desconocidos los datos no aportados. Solo se
pide una aclaración concreta si es imprescindible para seguridad o para aplicar un cambio.
Síntomas nuevos preocupantes bloquean la generación; no se sustituyen por una pregunta
que permita saltarse la protección. Las revisiones antiguas conservan sus respuestas.
Como alternativa textual se puede responder «terminé y todo bien» o «quiero ajustar algo».
El flujo se guarda y puede reanudarse. Los cambios confirmados de entrenamiento, sueño,
restricciones y objetivo se guardan como perfil efectivo; no se reinicia `/interview` ni se
reescribe el informe original del entrevistador.

La renovación recibe el perfil efectivo, el plan previo, sus series prescritas por target/semana
y la revisión. Con buena adherencia y recuperación conserva ejercicios útiles y progresa
gradualmente; con baja adherencia simplifica, y con fatiga reduce o mantiene estímulo.
El estancamiento no implica subir siempre el volumen. La descarga no es la base del nuevo bloque.
No se inventan cargas realizadas ni se garantiza mejoría. Nuevos síntomas preocupantes bloquean
la generación y requieren atención profesional.

El resultado es un **borrador no activo**, con informe de cambios y su justificación.
`/train confirmar PROPUESTA [AAAA-MM-DD]` lo activa y asigna una versión. La fecha opcional
es el inicio del nuevo mesociclo, en UTC; por defecto se usa la confirmación.
`/train cancelar` descarta la propuesta sin cambiar el plan. Confirmar dos veces no crea
dos versiones. Si cambió el plan base, la propuesta no puede activarse.
`/train editar CAMPO TEXTO` corrige una respuesta e invalida el borrador; los campos son
`adherence`, `results`, `recovery`, `discomfort`, `preferences` y `changes`.

## Sustituir un ejercicio

### Modelos y presupuestos por tarea

`ia_trainer_generation_model` selecciona el modelo de planes y propuestas de sustitución.
`ia_trainer_consultation_model` y `ia_trainer_extraction_model` seleccionan consulta/
detección e interpretación de revisión/restricciones respectivamente. Si se omiten,
cada uno usa `ia_model`. Consulta y extracción tienen overrides opcionales de
`max_tokens` y `timeout` con los mismos prefijos; sin overrides heredan
`ia_trainer_max_tokens` y `ia_trainer_timeout` (o `ia_timeout_seconds`).
No se activa un modelo rápido ni se recortan respuestas automáticamente.
Las cadenas y clientes siguen cacheados; reiniciar la app aplica cambios de entorno.

El presupuesto nominal de una tarea con reparación es
`2 × (1 + ia_max_retries) × timeout`; el backoff del proveedor y red pueden añadir
tiempo. No es un deadline del workflow. Un swap por texto puede además sumar detección,
extracción y propuesta. Mantener `ia_max_retries=0` y dimensionar presupuestos por
acción antes de elevarlos. Las llamadas fallidas y de reparación conservan tokens
y modelo en `token_usage`; no hay fallback silencioso a otro modelo.
Los valores comentados de `.env.example` son ejemplos, no límites de calidad validados.
Antes de activarlos, comparar salidas máximas, síntomas, material, esquemas y latencia
con los casos de línea base; ante regresión, retirar los overrides.

`/train cambiar` muestra un selector por botones con nombres y sesión de referencia,
paginado en grupos de ocho. Después permite elegir la semana y el motivo; solo solicita
texto para concretar material o un motivo libre. Las semanas ofrecidas contienen el
ejercicio seleccionado. En un borrador nuevo aplica desde la semana 1 por defecto.
Los callbacks verifican identidad, revisión, paso y pertenencia al plan.
Los mensajes naturales («quiero cambiar el press de banca», «no tengo barra, ¿podemos
sustituirlo?») se detectan en la consulta mediante `intent="exercise_swap"` y abren
el mismo selector, conservando el mensaje como motivo. No se exige un ID ni se ejecuta
una modificación por decisión del modelo. Se reutiliza la salida estructurada existente,
en lugar de añadir una tool con permisos de escritura; preguntas hipotéticas no deben
iniciar un cambio. El usuario confirma el ejercicio, el alcance y la propuesta.
Para intenciones de cambio/renovación no se muestra el texto libre del modelo:
el servicio envía exclusivamente el siguiente paso real. `swap_selection` recoge
semana explícita, ejercicio inequívoco del plan y motivo (o null si no se aportan).
Una semana indicada filtra los botones y evita preguntarla de nuevo; un ejercicio
identificado todavía requiere confirmación por botón. Los IDs ajenos al plan se
descartan con aviso en logs. Sin motivo explícito se ofrecen los botones de motivo,
en vez de tratar «quiero cambiar» como justificación. Se conserva el texto original
para las comprobaciones de seguridad y se contabiliza la llamada de detección.
También se puede usar `/train cambiar ID SEMANA MOTIVO`, por ejemplo
`/train cambiar 101 2 no dispongo de barra`.
La semana no se deduce como ejecución real a partir del calendario.

El RAG obtiene el ejercicio por id y busca alternativas del mismo target y grupo verificado,
excluyendo el original y filtrando el material declarado (no todo el gimnasio).
Si falta información o no hay candidatos adecuados, informa y no inventa alternativas.
La similitud semántica no certifica equivalencia biomecánica ni seguridad médica.
La propuesta incluye hasta tres opciones y ajustes conservadores de prescripción.

Antes de buscar, una extracción estructurada interpreta el motivo: identifica material
explícitamente no disponible y síntomas, distinguiendo «no tengo dolor» de dolor nuevo.
El material excluido se aplica como filtro estricto del RAG, sin modificar permanentemente
el perfil. Si la petición es ambigua, hace una pregunta concreta y guarda la respuesta;
los síntomas preocupantes bloquean el flujo hasta cancelarlo y obtener orientación adecuada.
Esta interpretación añade una llamada al LLM, contabilizada y sujeta a la cuota de generación.

La única excepción es «Prefiero otro ejercicio» elegido por botón, con procedencia
`preference_button` persistida por el backend. Sin texto natural, revisión previa,
aclaración, bloqueo, lesiones declaradas o flags rojas, omite la extracción y pasa
directamente al RAG y a la propuesta validada: una llamada LLM en vez de dos.
La propuesta conserva su comprobación de síntomas y el evaluador del plan completo.
Escribir el mismo texto no habilita la excepción. Los workflows antiguos y motivos
de dificultad/material/otros usan siempre la interpretación completa. Los modelos
actuales siguen siendo los mismos por defecto; no se presupone una reducción de
latencia del proveedor, solo se elimina una llamada en el caso seguro.

El modelo de alternativas recibe las sesiones afectadas completas, sus prescripciones
pendientes, el resumen semanal de series por target y metadatos/instrucciones del catálogo.
Prioriza función y patrón de movimiento cuando las instrucciones lo permiten, evita
redundancias y debe explicar equivalencias no verificables. No se añaden metadatos
biomecánicos inventados: la comprobación determinista sigue siendo target/grupo/material,
duplicados y las reglas del evaluador sobre el plan resultante.

`/train elegir PROPUESTA OPCIÓN` crea el borrador de sustitución y
`/train confirmar PROPUESTA` lo aplica. Cambia las ocurrencias desde la semana indicada;
las anteriores quedan intactas. Mantiene la progresión relativa de series y limita RPE,
incluida la descarga. Una sustitución crea una versión del **mismo mesociclo**, sin
reiniciar fechas. En una renovación, los cambios deseados se recogen en `preferences`
y pueden corregirse mediante `/train editar preferences ...` antes de aceptar.
Con el borrador ya generado, `/train cambiar ID SEMANA MOTIVO` ofrece también alternativas
RAG para ese borrador: indicar semana 1 aplica al nuevo bloque completo. Elegir una opción
actualiza el borrador, no abre versiones intermedias. Confirmarlo sigue siendo una renovación
con un nuevo mesociclo. El flujo conserva las trazas de generación y de las sustituciones.

## Fechas y avisos

`/progress` muestra el estado del mesociclo, no un registro detallado de rendimiento.
`/train posponer AAAA-MM-DD` fija otra fecha prevista cuando aún no se ha completado.
`/train avisos off|on` guarda la preferencia, que se conserva al renovar.

La interacción con el bot y un worker independiente comparten eventos PostgreSQL con
clave por ciclo/ocasión y leases. Hay una propuesta inicial por ciclo; solo una
posposición explícita habilita otra ocasión. El worker no llama al LLM.
Los avisos automáticos requieren `training_reminders_enabled=true`; ver
[entornos-y-despliegue.md](entornos-y-despliegue.md#worker-de-avisos-de-entrenamiento).

Los planes anteriores a esta funcionalidad conservan sus versiones, pero no se inventa
su fecha de inicio a partir de la creación. `/train inicio AAAA-MM-DD` confirma la fecha,
o `/train` permite confirmar que ya acabaron. Hasta entonces no reciben avisos por antigüedad.

La entrega externa es **al menos una vez**: un fallo después de enviar a Telegram y antes
de registrar éxito puede duplicar excepcionalmente un aviso. Las reservas evitan duplicados
normales entre workers/interacciones, no prometen exactamente una entrega externa.

## Comandos y estados

El primer `/train` genera y activa un plan. Repetirlo abre o reanuda revisión y renovación.
Solo aceptar un borrador crea la versión N+1 y actualiza el puntero vigente; las versiones
anteriores no se sobrescriben. Versión y mesociclo no son equivalentes: una sustitución
confirmada pertenece al mismo ciclo.

Un mensaje sin comando se enruta según dos estados:

| `interview_sessions.status` | `training_sessions.status` | Destino |
| --- | --- | --- |
| `null` | — | Arranca una entrevista |
| `in_progress` | — | `interviewer` |
| `completed` | `null` | Mensaje indicando que use `/train` |
| `completed` | `active` | `trainer`, modo preguntas |

Un flujo abierto de entrenamiento recibe las respuestas libres antes del modo preguntas.
Los comandos explícitos de consulta y control permiten consultar, corregir o cancelar.

`/interview` borra el historial, el perfil **y también el plan y la sesión de entrenamiento**: un
perfil nuevo invalida el mesociclo anterior.

## Selección del prompt

El código selecciona el prompt; el LLM no decide qué modo utilizar. `ConversationService` enruta
el mensaje según el comando y los estados de entrevista y entrenamiento:

| Entrada | Método de `TrainerChain` | Prompt y contexto |
| --- | --- | --- |
| `/train`, con perfil disponible | `generate_plan()` | `trainer/system_prompt.txt` + skill seleccionada + catálogo recuperado; el perfil se añade como mensaje. |
| Mensaje sin comando, con entrevista completada y entrenamiento activo | `answer()` | `trainer/answer_prompt.txt`; se añaden el historial, el plan guardado, el perfil disponible y la pregunta. Sin skill ni catálogo. |
| Revisión completa | `generate_next_plan()` | Prompt de generación + `renewal_prompt.txt`, contexto adaptativo y catálogo actualizado. |
| Interpretación de revisión | `extract_review()` | `review_prompt.txt` y esquema limitado de cambios de entrenamiento. |
| Petición de sustitución | `propose_swap()` | `swap_prompt.txt`, perfil y candidatos RAG filtrados. |

En generación, `ia_trainer_skill` selecciona `trainer` o `trainer-dev`. `PromptLoader` ensambla
`system_prompt.txt` con esa skill al crear la cadena y el catálogo se inserta en cada generación.
En consulta, `answer()` carga explícitamente el prompt independiente:

```python
self._loader.load_system_prompt("trainer", "answer_prompt.txt")
```

Ambos métodos usan el mismo modelo, pero cada petición lleva su propio `SystemMessage`: uno para
diseñar el mesociclo y otro para explicar el plan en modo de solo lectura. La consulta no reutiliza
el prompt de generación ni depende de que el modelo recuerde una petición anterior. Si hay que
reparar una respuesta inválida, se conservan el prompt y el contexto del modo correspondiente.

## Método de entrenamiento

El método de generación se define en dos recursos que se ensamblan al crear el agente:

| Recurso | Responsabilidad |
| --- | --- |
| `src/fitcoach/infrastructure/prompts/trainer/system_prompt.txt` | Rol, tono, límites de seguridad, contrato JSON y reglas del catálogo. |
| `src/fitcoach/infrastructure/ia/skills/trainer/SKILL.md` | Periodización, volumen, splits y sustituciones por lesión. No define el contrato JSON. |

La periodización es de cuatro semanas:

| Semana | `intensity` | Volumen respecto a la semana 1 |
| --- | --- | --- |
| 1 | `accumulation` | Base, como máximo `tolerable_volume_sets` por grupo muscular |
| 2 | `intensification` | ~110 %, o mismas series con más RPE |
| 3 | `peak` | ~120 %, RPE más alto del bloque |
| 4 | `deload` | ~50-60 %, RPE máximo 6 |

`commitment.days_per_week` y `minutes_per_session` son límites duros: el plan debe caber en el
tiempo que el usuario declaró tener.

`tolerable_volume_sets` es un techo de series de trabajo **por grupo muscular y por semana**.
Se suman las series de todos los días por separado para cada `target` del catálogo; no se divide
el valor entre grupos musculares ni se aplica como un total de cuerpo completo. No incluye series
de calentamiento ni obliga a alcanzar el techo. Por ejemplo, un techo de 5 permite hasta 5 series
de pecho y hasta 5 de espalda en la semana 1, no solo 5 series entre ambos. Las semanas 2-3 siguen
la progresión de la skill; con banderas rojas, el techo por grupo se mantiene las cuatro semanas.

Este significado se comparte con ambas skills del entrevistador y del entrenador. Cambiar los
prompts no recalcula perfiles ni planes ya guardados; una nueva entrevista y generación aplican
las instrucciones nuevas.

## Contrato entre el modelo y la aplicación

El modelo devuelve siempre un único objeto JSON. Al generar un plan:

```json
{
  "status": "plan",
  "reply": "Confirmación breve.",
  "report": "Resumen del mesociclo listo para Telegram.",
  "plan": { "...": "mesociclo validado" },
  "intent": "answer"
}
```

Al responder una pregunta sobre el plan:

```json
{
  "status": "answer",
  "reply": "Respuesta breve.",
  "report": null,
  "plan": null,
  "intent": "answer"
}
```

`TrainerTurn` valida el contrato con Pydantic:

`intent` puede ser `answer`, `renewal` o `exercise_swap` en consulta; solo enruta
al flujo correspondiente, no autoriza cambios. En generación se usa `answer`.
Para respuestas antiguas sin este campo se conserva el valor por defecto `answer`.

- `plan` exige `report` y `plan`; `answer` prohíbe ambos.
- `weeks` debe tener exactamente 4 entradas, numeradas 1-4 y en orden.
- Cada semana debe tener exactamente `days_per_week` días, con valores de `day` distintos.

En consulta se valida con `TrainerAnswerTurn`, que solo permite `status=answer`, `report=null` y
`plan=null`. Si el modelo intenta devolver un plan, se solicita una reparación conservando el
contexto de consulta; si vuelve a incumplir, se informa del error al usuario. Solo la generación
produce trazas de planes; las consultas mantienen el registro habitual de mensajes y tokens.

### Anclaje al catálogo

Además de lo que Pydantic puede comprobar, `TrainerChain` valida que todo `exercise_id` del plan
pertenezca al conjunto que devolvió la recuperación. Un plan con ejercicios inventados cumple el
esquema y aun así no sirve, así que se rechaza como error de validación y pasa por el mismo camino
de reparación que un JSON malformado. Si tras la reparación sigue inventando, no se persiste nada y
el usuario recibe un mensaje para reintentar.

La reparación continúa la conversación original (system prompt con `<rag_context>`, perfil, la
respuesta inválida y los errores concretos), así el modelo sigue viendo qué ids son válidos.

El conjunto permitido se pasa por parámetro en cada petición, no se guarda en la cadena: las
cadenas son *singletons* compartidos entre peticiones concurrentes.

## Recuperación (RAG)

| Componente | Ubicación |
| --- | --- |
| Consulta a partir del perfil y bloque de contexto | `src/fitcoach/service/agent/rag_context.py` |
| Una consulta por grupo muscular, deduplicada | `src/fitcoach/service/agent/exercise_retriever.py` |
| Cliente HTTP del servicio de embeddings | `src/fitcoach/infrastructure/ia/embedder_client.py` |
| Búsqueda semántica en pgVector | `src/fitcoach/infrastructure/vectordb/pgvector_exercise_repository.py` |

El texto de consulta se construye con **el mismo formato** que `build_metadata_text()` del cargador
(`name: ... | category: ... | ...`). No es un detalle estético: si cambia, la consulta deja de vivir
en el mismo espacio semántico que el corpus. Ver [vector-db.md](vector-db.md).

Antes de ordenar por distancia coseno se aplica un prefiltro SQL barato por equipamiento, derivado
de `training.environment`. Quien entrena en gimnasio no se filtra: solo costaría recall.

El contenido de `exercises` es **dato, nunca instrucción**. El prompt lo declara así y, además, el
constructor del bloque elimina caracteres de control y trunca las instrucciones.

### Degradación

| Situación | `/train` | Modo preguntas |
| --- | --- | --- |
| Embedder o pgVector caídos | Falla con mensaje de reintento | No depende de estos servicios |
| Catálogo vacío | Falla con mensaje de reintento | No consulta el catálogo |

La asimetría es deliberada: un mesociclo sin catálogo de ejercicios es exactamente lo que este
agente existe para evitar, mientras que una pregunta se puede responder desde el plan ya guardado.

## Persistencia

| Tabla | Contenido | Cuándo se actualiza |
| --- | --- | --- |
| `training_plans` | Plan JSON e informe, versionados por `chat_id`, con ciclo y plan padre. | Primer plan o confirmación de un borrador. |
| `training_sessions` | Estado `active` y puntero autoritativo del vigente. | Primera activación o confirmación. |
| `training_mesocycles` | Inicio, fin previsto, cierre declarado y preferencias de avisos. | Inicio, cierre, renovación o controles de fechas. |
| `training_workflows` | Revisión, perfil efectivo, candidatos, borrador, estado y aprobación. | En cada avance del flujo; conserva los cerrados. |
| `training_notifications` | Eventos de aviso, ocasión, intentos y lease. | Detección, envío, reintento o posposición. |
| `conversation_messages` | Turnos, con la columna `agent` que separa entrevista de entrenamiento. | En cada turno válido. |
| `token_usage` | Una fila por llamada al modelo, con `agent = 'trainer'`. | En cada llamada, incluidas las fallidas. |

La columna `agent` de `conversation_messages` es imprescindible: sin ella, el modo preguntas del
entrenador heredaría toda la transcripción de la entrevista. La migración la añade con
`server_default = 'interviewer'`, que es lo correcto para las filas anteriores.

## Errores

El entrenador reutiliza la taxonomía de errores compartida (`domain/agent_errors.py`), la misma que
el interviewer: `llm_authentication`, `llm_quota`, `llm_rate_limited`, `llm_invalid_request`,
`llm_output_limit`, `llm_timeout`, `llm_unavailable` y `llm_invalid_output`. Los fallos del servicio
de embeddings se traducen a esos mismos códigos, de modo que un embedder caído se comunica al
usuario igual que un proveedor de modelo caído: un mensaje seguro, sin cuerpos HTTP ni credenciales.

`llm_output_limit` es especialmente relevante aquí: un mesociclo completo necesita muchos más tokens
que una pregunta de entrevista. Por eso el entrenador usa `ia_trainer_max_tokens` (4096 por defecto)
en vez de `ia_max_tokens`.

## Observabilidad

El span `conversation.turn` añade, además de los atributos habituales:

| Atributo | Significado |
| --- | --- |
| `agent` | `trainer` |
| `rag.exercises_retrieved` | Ejercicios recuperados y entregados al modelo |
| `rag.latency_ms` | Tiempo de embeddings más consulta a pgVector |
| `rag.degraded` | `false` en generación; no se emite en consultas |

Los atributos `rag.*` corresponden a generación, no a consultas: estas no realizan recuperación.

## Depuración offline del prompt y la skill

`fitcoach.devtools.trainer_debug` ejecuta el entrenador sin Telegram ni BD de conversaciones: una
ejecución depende solo de (perfil, catálogo, variante de prompt/skill, modelo), así que se puede
repetir mientras se ajusta el `SKILL.md` o el `system_prompt.txt`. La cadena se construye en cada
ejecución, de modo que los cambios en disco se aplican sin reiniciar nada.

Los casos del *golden set* viven en [`evals/trainer/cases`](../evals/trainer/README.md): cada uno es
un `profile.json` y el `catalogue.json` congelado que devolvió la recuperación real para ese perfil.
Los targets `trainer-debug`, `trainer-compare` y `trainer-refresh-catalogues` usan el entorno de
desarrollo del Makefile (`/etc/fitcoachia/dev/.env.dev`, o `.env.dev` del repositorio como fallback).

```bash
# Solo renderiza el prompt que se enviaría (sin llamar al LLM, sin coste)
make trainer-debug ARGS="--case-dir evals/trainer/cases/beginner_gym_lose_fat --render-only"

# Ejecución completa con una copia de la skill que se está editando
make trainer-debug ARGS="--case-dir evals/trainer/cases/knee_injury_home \
  --skills-root /tmp/skills --skill trainer --variant v2"

# Reproducir el caso real de un usuario: perfil desde la BD, catálogo desde pgVector
make trainer-debug ARGS="--chat-id 123 --live-retrieval --save-catalogue evals/trainer/catalogue_123.json"
```

| Opción | Uso |
| --- | --- |
| `--case-dir` | Carpeta de un caso con `profile.json` y `catalogue.json` |
| `--profile` / `--chat-id` | Perfil desde un JSON o desde `interviewer_profiles` |
| `--catalogue` / `--live-retrieval` | Catálogo congelado o recuperación real (embedder + pgVector) |
| `--top-k` | Ejercicios por grupo muscular en la recuperación real (por defecto `ia_rag_top_k`) |
| `--save-catalogue` | Congela el catálogo usado para repetir la ejecución |
| `--prompts-root` / `--skills-root` / `--skill` | Variante de `trainer/system_prompt.txt` y `<skill>/SKILL.md` |
| `--model` / `--temperature` / `--max-tokens` | Sobrescriben `ia_model`, `ia_temperature`, `ia_trainer_max_tokens` |
| `--timeout SECONDS` | Sobrescribe `ia_trainer_timeout` con un entero positivo para cada petición al LLM |
| `--render-only` | Escribe el prompt y los mensajes sin llamar al modelo |
| `--evaluate-run DIR` | Vuelve a puntuar una ejecución guardada sin llamar al modelo |

`trainer-debug` y `trainer-compare` muestran el inicio de cada llamada, las reparaciones y un
aviso cada 10 segundos mientras esperan la respuesta. Estos mensajes van a stderr; no son tokens
en streaming ni muestran el razonamiento interno del modelo. El timeout se aplica a cada petición,
no a la ejecución completa: una reparación y los reintentos configurados pueden aumentar el total.

```bash
make trainer-debug ARGS="--case-dir evals/trainer/cases/knee_injury_home --timeout 300"
```

Cada ejecución crea `runs/trainer/<fecha>-<caso>-<variante>/` (ignorado por git) con:

- `system_prompt.txt`: el prompt exacto enviado (skill y catálogo incluidos).
- `calls/NN_request.json` y `calls/NN_response.txt`: cada llamada, incluida la reparación.
- `plan.json` y `plan.md`: el turno validado y una vista legible por semanas y días.
- `evaluation.json` y `evaluation.md`: el resultado del evaluador (ver abajo).
- `run.json`: estado, error, llamadas, tokens, latencia, `score`, `eval_errors`, `eval_warnings` y
  huella (`prompt_fingerprint`) del prompt.
- `profile.json` y `catalogue.json`: las entradas, para repetir la ejecución.

El proceso termina con código 0 si se generó un plan y 1 en otro caso. Con `--evaluate-run`, 0 si el
plan no tiene errores del evaluador y 1 si los tiene.

### Evaluador determinista

La [guía del evaluador de planes](plan-evaluator.md) detalla su flujo, reglas y umbrales, métricas,
limitaciones y uso para volver a evaluar ejecuciones guardadas sin llamar al LLM.

Pydantic garantiza la *forma* del plan; `service/agent/plan_evaluator.py` comprueba las reglas de la
skill que el esquema no puede expresar y devuelve hallazgos en lugar de lanzar excepciones, para
poder puntuar un plan y comparar variantes sobre los mismos casos. Puntuación: `100 − 15·errores −
3·avisos` (mínimo 0); un plan *pasa* si no tiene errores.

| Severidad | Reglas |
| --- | --- |
| `error` (incumple una regla explícita) | `profile_mismatch` (objetivo, entorno o días distintos del perfil), `unknown_exercise_id`, `name_mismatch`, `session_over_budget` (`estimated_minutes` > `minutes_per_session`), `duplicate_exercise_in_day`, `volume_over_ceiling` (series semanales por músculo `target` > `tolerable_volume_sets` en la semana 1, o en todas con banderas rojas), `deload_volume` (semana 4 ≥ semana 1), `rpe_over_cap` (S1 > 8, S3 > 9, S4 > 6), `injury_not_recorded`, `red_flags_maximal_effort` (RPE ≥ 9), `red_flags_no_referral`, `report_over_telegram_limit` (4096), `no_plan` |
| `warning` (heurística, revisar a mano) | `session_time_formula_over_budget` (fórmula de la skill con 40 s por serie, +15 % de tolerancia), `no_progression` (S2 y S3 no suben volumen ni RPE), `deload_volume` fuera del 40-70 %, `reps_outside_goal_range` / `rest_outside_goal_range` (semana 1), `exercises_change_between_weeks` (< 50 % de ejercicios conservados), `group_not_trained` (pecho, espalda o piernas, si el catálogo los tiene), `phantom_injury_exclusion`, `possible_injury_conflict` (palabras clave por zona lesionada), `reply_too_long` (> 600) |
| `info` (catálogo) | `catalogue_missing_group` y `group_not_trained` cuando el catálogo tampoco tiene el grupo: el problema es la recuperación, no el prompt |

Las métricas (`weekly_sets`, `mean_rpe`, `week1_sets_per_target`, `max_formula_minutes`,
`exercises_per_day`, `distinct_exercises`, grupos del catálogo...) ayudan a ver *por qué* cambia la
puntuación entre variantes. Tras añadir o ajustar una regla, `--evaluate-run` re-puntúa ejecuciones
antiguas sin gastar tokens.

### Comparar skills y modelos

```bash
make trainer-compare ARGS="--skill trainer --skill trainer-dev"
make trainer-compare ARGS="--skill trainer --skill trainer-dev \
  --model modelo-a --model modelo-b"
```

`trainer-compare` ejecuta el producto cartesiano de skills y modelos sobre todos los casos de
`evals/trainer/cases`. Conserva los artefactos de cada ejecución y escribe `comparison.md`,
`comparison.csv` y `comparison.json` con puntuación, errores, avisos, reparaciones, tokens y
latencia por caso y agregados por variante. Una puntuación baja no hace fallar el comando — es el
resultado que se quiere comparar—; el código de salida es 1 solo si alguna ejecución no pudo
producir una respuesta validada.

### Trazabilidad de planes en producción

Cada fila nueva de `training_plans` conserva, además del plan y el informe:

- modelo y nombre de la skill;
- SHA-256 del system prompt exacto enviado (skill y catálogo RAG incluidos);
- SHA-256 del contenido de la skill;
- ids de los ejercicios recuperados.

Estos campos permiten identificar la variante que produjo un fallo y reconstruir su catálogo sin
guardar el prompt, el perfil ni la salida bruta por duplicado. Las filas anteriores a la migración
mantienen estos campos a `null`.

## Componentes principales

| Componente | Ubicación |
| --- | --- |
| Orquestación, comandos y enrutado | `src/fitcoach/service/conversation_service.py` |
| Invocación LangChain y anclaje al catálogo | `src/fitcoach/service/agent/trainer_chain.py` |
| Plumbing compartido entre agentes | `src/fitcoach/service/agent/llm_chain.py` |
| Contrato Pydantic del plan | `src/fitcoach/domain/trainer_plan.py` |
| Repositorio PostgreSQL | `src/fitcoach/infrastructure/database/postgres_conversation_repository.py` |
| Sesión de la BD vectorial | `src/fitcoach/infrastructure/vectordb/session.py` |
| Depuración offline (CLI y runner) | `src/fitcoach/devtools/` |
| Evaluador de reglas de la skill | `src/fitcoach/service/agent/plan_evaluator.py` |

## Configuración

```dotenv
# Agente 2 (entrenador)
ia_trainer_skill=trainer
ia_trainer_max_tokens=4096
ia_trainer_history_window_messages=10
ia_rag_top_k=8

# Base de datos vectorial (solo lectura)
vector_db_url=postgresql+asyncpg://fitcoach_ro:<secreto>@pgvector:5432/fitcoach

# Servicio de embeddings
embedder_url=http://embedder:8100
embedder_timeout_seconds=10
```

El arranque falla rápido si falta `vector_db_url` o `embedder_url`.

En desarrollo, `docker-compose.dev.yml` fija `ia_trainer_skill=trainer-dev`. Esa variante desarrolla
bien la semana 1 y deriva las otras tres, con un máximo de 3 ejercicios por día. Sirve para probar
el flujo y la persistencia sin gastar 4096 tokens por iteración; no debe usarse en producción.

Para levantar la base de datos vectorial en local: `make vector-up` (ver [vector-db.md](vector-db.md)).

No incluyas `ia_token`, credenciales de base de datos, perfiles, planes ni datos sanitarios en
commits, logs públicos, tickets o conversaciones no protegidas.
