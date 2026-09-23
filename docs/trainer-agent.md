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
7. Envía el informe al usuario y persiste el plan como una nueva versión.

Los mensajes posteriores, mientras la sesión de entrenamiento está `active`, van al modo preguntas:
misma cadena, con el plan vigente e historial propio del agente.

## Comandos y estados

`/train` genera un plan nuevo. Repetirlo **no sobrescribe** el anterior: crea la versión N+1 y la
sesión apunta a ella. Así el Agente 3 (Nutricionista) podrá consultar el volumen de entrenamiento
sobre el que se calculó una dieta.

Un mensaje sin comando se enruta según dos estados:

| `interview_sessions.status` | `training_sessions.status` | Destino |
| --- | --- | --- |
| `null` | — | Arranca una entrevista |
| `in_progress` | — | `interviewer` |
| `completed` | `null` | Mensaje indicando que use `/train` |
| `completed` | `active` | `trainer`, modo preguntas |

`/interview` borra el historial, el perfil **y también el plan y la sesión de entrenamiento**: un
perfil nuevo invalida el mesociclo anterior.

## Método de entrenamiento

El comportamiento se define en dos recursos que se ensamblan al crear el agente:

| Recurso | Responsabilidad |
| --- | --- |
| `src/fitcoach/infrastructure/prompts/trainer/system_prompt.txt` | Rol, tono, límites de seguridad, contrato de integración y reglas del catálogo. |
| `src/fitcoach/infrastructure/ia/skills/trainer/SKILL.md` | Periodización, volumen, splits, sustituciones por lesión y estructura del plan. |

La periodización es de cuatro semanas:

| Semana | `intensity` | Volumen respecto a la semana 1 |
| --- | --- | --- |
| 1 | `accumulation` | 100 % de `initial_calculations.tolerable_volume_sets` |
| 2 | `intensification` | ~110 %, o mismas series con más RPE |
| 3 | `peak` | ~120 %, RPE más alto del bloque |
| 4 | `deload` | ~50-60 %, RPE máximo 6 |

`commitment.days_per_week` y `minutes_per_session` son límites duros: el plan debe caber en el
tiempo que el usuario declaró tener.

## Contrato entre el modelo y la aplicación

El modelo devuelve siempre un único objeto JSON. Al generar un plan:

```json
{
  "status": "plan",
  "reply": "Confirmación breve.",
  "report": "Resumen del mesociclo listo para Telegram.",
  "plan": { "...": "mesociclo validado" }
}
```

Al responder una pregunta sobre el plan:

```json
{
  "status": "answer",
  "reply": "Respuesta breve."
}
```

`TrainerTurn` valida el contrato con Pydantic:

- `plan` exige `report` y `plan`; `answer` prohíbe ambos.
- `weeks` debe tener exactamente 4 entradas, numeradas 1-4 y en orden.
- Cada semana debe tener exactamente `days_per_week` días, con valores de `day` distintos.

### Anclaje al catálogo

Además de lo que Pydantic puede comprobar, `TrainerChain` valida que todo `exercise_id` del plan
pertenezca al conjunto que devolvió la recuperación. Un plan con ejercicios inventados cumple el
esquema y aun así no sirve, así que se rechaza como error de validación y pasa por el mismo camino
de reparación que un JSON malformado. Si tras la reparación sigue inventando, no se persiste nada y
el usuario recibe un mensaje para reintentar.

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
| Embedder o pgVector caídos | Falla con mensaje de reintento | Responde sin catálogo (`rag.degraded=true`) |
| Catálogo vacío | Falla con mensaje de reintento | Responde sin catálogo |

La asimetría es deliberada: un mesociclo sin catálogo de ejercicios es exactamente lo que este
agente existe para evitar, mientras que una pregunta se puede responder desde el plan ya guardado.

## Persistencia

| Tabla | Contenido | Cuándo se actualiza |
| --- | --- | --- |
| `training_plans` | Plan JSON e informe, versionados por `chat_id`. | En cada `/train` correcto. |
| `training_sessions` | Estado `active` y plan vigente. | Al generar o regenerar un plan. |
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
| `rag.degraded` | `true` si se respondió sin catálogo |

## Componentes principales

| Componente | Ubicación |
| --- | --- |
| Orquestación, comandos y enrutado | `src/fitcoach/service/conversation_service.py` |
| Invocación LangChain y anclaje al catálogo | `src/fitcoach/service/agent/trainer_chain.py` |
| Plumbing compartido entre agentes | `src/fitcoach/service/agent/llm_chain.py` |
| Contrato Pydantic del plan | `src/fitcoach/domain/trainer_plan.py` |
| Repositorio PostgreSQL | `src/fitcoach/infrastructure/database/postgres_conversation_repository.py` |
| Sesión de la BD vectorial | `src/fitcoach/infrastructure/vectordb/session.py` |

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
