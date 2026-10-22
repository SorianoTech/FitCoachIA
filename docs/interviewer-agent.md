# Agente `interviewer`

`interviewer` es el agente de bienvenida de FitCoachIA. Recopila los datos iniciales necesarios
para personalizar un plan de entrenamiento, nutrición y suplementación, detecta señales que
requieren precaución y construye un perfil estructurado por cada chat de Telegram.

No diagnostica, prescribe ni sustituye a profesionales sanitarios. Ante señales de riesgo, su
función es comunicarlo con empatía y recomendar atención profesional.

## Flujo de una conversación

1. Telegram entrega un update en `POST /webhook/response`.
2. `ConversationService` identifica el chat y procesa el comando o mensaje.
3. Para una entrevista activa, carga como máximo `ia_history_window_messages` mensajes recientes
   de ese `chat_id`.
4. `InterviewerChain` compone el prompt de sistema, el historial y el nuevo mensaje del usuario;
   los entrega al modelo OpenAI-compatible configurado.
5. Valida el JSON que devuelve el modelo. Si no cumple el contrato, solicita una única reparación.
6. Envía al usuario la respuesta conversacional y persiste el turno. Al finalizar, además guarda el
   perfil y el informe.

El webhook responde `200` una vez procesado el update, incluso si falla una dependencia. Así evita
que Telegram reintente indefinidamente el mismo mensaje.

## Inicio, estado y reinicio

El comando `/interview` borra el historial, la sesión y el perfil anteriores del chat, crea una
nueva sesión con estado `in_progress` y pide al agente que formule la pregunta de apertura.

Cuando un usuario escribe sin tener sesión, el servicio inicia una automáticamente. Si el estado
es `completed`, los mensajes normales no reabren la entrevista: se le indica al usuario que use
`/train` para generar su plan, o `/interview` para sustituir su perfil por una entrevista nueva.

Una vez existe un plan de entrenamiento, esos mensajes dejan de llegar aquí y los atiende el
agente [`trainer`](trainer-agent.md). Ten en cuenta que `/interview` borra también el plan y la
sesión de entrenamiento: un perfil nuevo invalida el mesociclo anterior.

El aislamiento es por `chat_id`: un chat nunca incorpora el historial o perfil de otro.

## Entrevista y reglas de conversación

El comportamiento se define en dos recursos que se ensamblan al crear el agente:

| Recurso | Responsabilidad |
|---|---|
| `src/fitcoach/infrastructure/prompts/interviewer/system_prompt.txt` | Rol, tono, límites de seguridad, idioma, contrato JSON y estructura del perfil. |
| `src/fitcoach/infrastructure/ia/skills/interviewer/SKILL.md` | Orden de preguntas, validaciones, señales de riesgo y método de estimación. |

La habilidad guía una entrevista ordenada de estas áreas:

0. Identidad o nombre preferido.
1. Edad, peso, altura y percepción corporal.
2. Objetivo principal, secundario y horizonte temporal.
3. Actividad diaria y nivel de NEAT.
4. Patrón de alimentación y alimentos problemáticos.
5. Digestión y energía.
6. Lesiones, dolor y restricciones.
7. Experiencia de entrenamiento y equipamiento.
8. Sueño y recuperación.
9. Suplementación, presupuesto y restricciones.
10. Compromiso real: días, tiempo y flexibilidad.

Debe hacer un paso de la skill por mensaje (la pregunta del paso puede pedir sus datos relacionados
juntos, p. ej. edad, peso, altura y sexo, pero nunca mezcla dos pasos; las repreguntas van en otro
mensaje), aprovechar datos adelantados por el usuario sin
repetirlos y formular aclaraciones cuando sean necesarias. El prompt exige responder siempre en
español, sea cual sea el idioma del usuario y aunque pida cambiarlo, sin términos híbridos de otros
idiomas (p. ej. «intervista»); también exige respuestas breves aptas para Telegram y un trato no
juzgador. El mensaje semilla de `/interview` (`INTERVIEW_SEED_MESSAGE`) también está en español
para no arrastrar al modelo a otro idioma.

Cálculos iniciales (definidos en la skill, para que sean reproducibles): `bmi` = kg / m²;
`bmr` con Mifflin-St Jeor (el sexo se pregunta solo para esto, no se guarda en el perfil; si no se
da, se usa el punto medio −78); `estimated_tdee` = `bmr` × (base NEAT + 0,03 × días por semana), con
base NEAT 1,2 / 1,35 / 1,5 para `sedentary` / `active` / `very_physical`. Son estimaciones y el
`report` declara el método. Ante síntomas digestivos la skill solo deriva a un profesional: no
propone dietas de eliminación. Si la skill choca con las barreras de seguridad o el contrato de
salida del prompt, prevalecen estos últimos.

Las preguntas de la skill están escritas en inglés como referencia y siempre se formulan en
español. La skill también define cómo se derivan `timeframe_weeks`, `realistic_expectation`,
`perceived_composition` y `estimated_composition`; P6 recoge además condiciones médicas, cirugías
recientes y mareos (se reflejan en `flags` y `report`, no hay campo propio); tras la respuesta a P10
se devuelve `completed` en el mismo turno; y ante señales de TCA o desesperanza se interrumpe la
recogida de datos y se deriva a un profesional. `registration_date` no lo inventa el modelo:
`InterviewerChain` añade al final del system prompt `CURRENT DATETIME (UTC)` en cada llamada.

Los mensajes del usuario y el historial se tratan como datos, nunca como instrucciones que puedan
alterar el rol o revelar la configuración. El entrevistador no usa RAG: su prompt no contiene
`rag_context` ni consulta catálogos. El agente [`trainer`](trainer-agent.md) usa el catálogo solo
al generar un plan.

El system prompt define el contrato JSON y todos los campos del perfil para ambas variantes.
La skill seleccionada define el flujo y las estimaciones: `interviewer` realiza la entrevista
completa; `interviewer-dev` usa tres preguntas y declara sus valores de prueba en el informe. En `interviewer-dev`, los datos básicos (nombre, edad,
peso, altura, objetivo, días y minutos) los aporta siempre el usuario: si faltan o están fuera de
rango se repreguntan una vez; los valores de prueba solo cubren lo que no se pregunta. Calcula
`bmi`, `bmr` (Mifflin-St Jeor con el punto medio −78, al no preguntar el sexo) y `estimated_tdee`
con las mismas fórmulas que la skill completa, y mantiene la detección de banderas rojas por IMC.

`initial_calculations.tolerable_volume_sets` significa techo de series de trabajo **por grupo
muscular y por semana**, no un total para todo el cuerpo ni un presupuesto por sesión. No incluye
calentamiento. La skill completa estima ese techo según experiencia y recuperación, justificando
las reducciones. La variante dev usa `10` como supuesto de prueba cuando falta esa información,
no como cálculo biométrico; respeta las limitaciones explícitas y comunica el supuesto.

## Contrato entre el modelo y la aplicación

El modelo no responde directamente con texto libre: siempre devuelve un único objeto JSON, sin
bloques Markdown.

Mientras continúa la entrevista:

```json
{
  "status": "in_progress",
  "reply": "Respuesta breve y la siguiente pregunta."
}
```

Al recopilar todos los datos obligatorios:

```json
{
  "status": "completed",
  "reply": "Confirmación breve de que la entrevista terminó.",
  "report": "Resumen empático listo para Telegram.",
  "profile": {
    "...": "perfil validado"
  }
}
```

`InterviewerTurn` valida este contrato con Pydantic:

- `in_progress` no puede contener `report` ni `profile`.
- `completed` exige ambos.
- `profile` debe cumplir el modelo estricto `InterviewerProfile`: biometría, objetivos, actividad,
  nutrición, digestión, lesiones, entrenamiento, sueño, suplementación, compromiso, flags y
  cálculos iniciales.

El informe se muestra en Telegram; el JSON del perfil queda almacenado en PostgreSQL. Si la primera
respuesta no se puede validar, `InterviewerChain` pide al modelo una única reparación. Si también
falla, no se guarda el turno y el usuario recibe un mensaje para reintentar.

## Persistencia

PostgreSQL conserva tres tipos de información:

| Tabla | Contenido | Cuándo se actualiza |
|---|---|---|
| `conversation_messages` | Mensajes del usuario y respuestas del agente. | En cada turno válido. |
| `interview_sessions` | Estado `in_progress` o `completed` y fechas. | Al comenzar, reiniciar o completar. |
| `interviewer_profiles` | Perfil JSON final e informe. | Solo al completar la entrevista. |

La columna `agent` de `conversation_messages` vale `interviewer` en estos turnos: separa el
historial de cada agente para que el entrenador no herede la transcripción de la entrevista.

La consulta de historial ordena los últimos mensajes por identificador y los devuelve en orden
cronológico para conservar el contexto del modelo. Consulta [how-to.md](how-to.md#consultar-la-base-de-datos-con-adminer)
para visualizar estas tablas con Adminer en desarrollo.

## Errores del proveedor

Las excepciones de OpenAI/OpenRouter se convierten en errores de aplicación antes de llegar a
Telegram. El usuario recibe un mensaje seguro sin cuerpos HTTP, credenciales ni texto interno del
proveedor.

| Código | Situación |
|---|---|
| `llm_authentication` | Credenciales inválidas o sin permisos (`401`/`403`). |
| `llm_quota` | Sin crédito disponible (`402`). |
| `llm_rate_limited` | Límite de solicitudes (`429`). |
| `llm_invalid_request` | Petición rechazada (`400`/`422`). |
| `llm_output_limit` | La generación alcanzó el máximo de tokens. |
| `llm_timeout` | Tiempo de respuesta agotado. |
| `llm_unavailable` | Error de conexión o indisponibilidad temporal del proveedor. |
| `llm_invalid_output` | Contenido no textual o JSON inválido tras el intento de reparación. |

El límite de salida es especialmente relevante al finalizar: el perfil completo requiere más tokens
que una pregunta normal. Configura `ia_max_tokens` en `.env.dev` con margen suficiente para el
informe y el perfil; `2048` es un punto de partida razonable y algunos modelos necesitarán `4096`.
Reinicia el entorno con `make dev-down && make dev-up` tras cambiar la configuración.

Para `gpt-5-nano-2025-08-07`, el razonamiento no configurado usa esfuerzo `medium`.
FitCoachIA envía `reasoning_effort=minimal` por defecto para reducir tiempo hasta la respuesta y
consumo en una tarea principalmente conversacional y de extracción. Puede ajustarse a `low`,
`medium` o `high`; el valor `default` omite el parámetro si el proveedor OpenAI-compatible no lo
admite. Reducirlo no evita un timeout causado por indisponibilidad o saturación del proveedor.

## Componentes principales

| Componente | Ubicación |
|---|---|
| Webhook de Telegram | `src/fitcoach/api/webhook.py` |
| Orquestación de comandos, Telegram y persistencia | `src/fitcoach/service/conversation_service.py` |
| Invocación LangChain, validación y errores del modelo | `src/fitcoach/service/agent/interviewer_chain.py` |
| Perfil y sobre de respuesta Pydantic | `src/fitcoach/domain/interviewer_profile.py` |
| Códigos de error seguros (compartidos entre agentes) | `src/fitcoach/domain/agent_errors.py` |
| Invocación, conteo de tokens y validación comunes | `src/fitcoach/service/agent/llm_chain.py` |
| Repositorio PostgreSQL | `src/fitcoach/infrastructure/database/postgres_conversation_repository.py` |

## Configuración

El modelo se configura con estas variables, normalmente en `.env.dev`:

```dotenv
ia_base_url=https://.../v1
ia_token=<secreto>
ia_model=<proveedor/modelo>
ia_temperature=0.5
ia_interviewer_reasoning_effort=minimal
ia_timeout_seconds=60
ia_max_tokens=2048
ia_history_window_messages=20
ia_skill=interviewer
```

En desarrollo, `docker-compose.dev.yml` establece automáticamente `ia_skill=interviewer-dev`.
Esa variante pregunta solo identidad, datos básicos y objetivo/compromiso, y después genera el
mismo perfil estructurado y el informe final usando valores conservadores para los campos que no
se preguntan. Sirve para probar rápidamente la persistencia y el flujo de finalización; no debe
usarse en producción.

No incluyas `ia_token`, perfiles, informes ni datos sanitarios en commits, logs públicos, tickets o
conversaciones no protegidas. Si una credencial se expone, revócala y genera otra.
