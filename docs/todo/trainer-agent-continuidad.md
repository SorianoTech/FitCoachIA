# Plan de implementacion: continuidad del entrenador y renovacion de mesociclos

## Objetivo

Detectar que un mesociclo podria haber terminado, confirmar su cierre con el usuario,
recoger una revision breve y generar un borrador adaptado al perfil vigente y al plan
anterior. Activarlo exclusivamente tras confirmacion. Permitir tambien sustituciones
de ejercicios durante el mesociclo y durante la revision del siguiente, con alternativas
del catalogo RAG y versionado inmutable.

Este documento es un plan; no se han modificado archivos del proyecto.

## Decisiones confirmadas con el usuario

- Deteccion tanto al interactuar con el bot como mediante avisos programados.
- Fecha prevista mas confirmacion del usuario, sin diario de sesiones en esta entrega.
- Revision breve obligatoria antes de renovar.
- Renovaciones como borrador; activacion solo tras confirmacion.
- Primer `/train` conserva la activacion inmediata actual.
- Proceso periodico independiente de FastAPI, coordinado mediante PostgreSQL.
- Cada sustitucion confirmada crea una version, pero mantiene el mismo mesociclo.
- Sustituciones durante el bloque y al renovarlo. Por defecto afectan las semanas
  pendientes, con semana actual y alcance confirmados por el usuario.
- Avisos controlados: una propuesta inicial por mesociclo, con posposicion y desactivacion.

## Estado actual comprobado

| Componente | Comportamiento actual y consecuencia |
| --- | --- |
| `domain/trainer_plan.py` | Contrato estricto de cuatro semanas: accumulation, intensification, peak y deload. Solo admite generacion o consulta. No contiene ejecucion real ni fechas. |
| `infrastructure/database/models.py` | La tabla real se llama `training_plans`. Versiones unicas por chat y `training_sessions.current_plan_id`; no hay ciclo, revision ni borrador. |
| `infrastructure/database/postgres_conversation_repository.py` | `save_training_plan()` incrementa la version bajo advisory lock y activa inmediatamente. `get_current_plan()` devuelve la mayor version, no el plan apuntado por la sesion. Esto debe corregirse para separar vigente y propuestas. |
| `service/conversation_service.py` | `/train` genera desde el perfil y RAG, sin cargar el plan previo. Los mensajes libres del entrenamiento activo son consultas de solo lectura. `/progress` no esta implementado. |
| `service/agent/trainer_chain.py` | `generate_plan(profile, exercises)` no recibe resultados anteriores. `answer()` usa otro prompt y `TrainerAnswerTurn`, que prohibe modificar planes. Valida ids recuperados y permite una reparacion. |
| `service/agent/exercise_retriever.py` | Consulta semantica por grupo, pero el grupo solo aparece en el texto de embedding, no como filtro SQL. |
| `repository/exercise_repository.py`, `infrastructure/vectordb/pgvector_exercise_repository.py` | Busqueda por similitud con filtro opcional de equipamiento; faltan consulta por ids, exclusion de ids y filtros explicitos de grupo/target. |
| `service/agent/rag_context.py` | Equipamiento permitido se deriva del entorno: un gimnasio no filtra y en casa se permiten categorias amplias. Para alternativas debe respetarse el material realmente declarado. |
| `domain/exercise.py`, `infrastructure/vectordb/models.py` | Existen grupo, target, body_part, material e instrucciones. No hay metadatos estructurados fiables sobre patron de movimiento, dificultad o contraindicaciones clinicas. |
| `service/agent/plan_evaluator.py` | Ya calcula volumen, cobertura, tiempos y restricciones. Su uso identificado esta en herramientas de evaluacion; no bloquea actualmente la generacion en produccion. Algunas reglas son heuristicas, no garantias clinicas. |
| `main.py`, `docker-compose*.yml`, `src/Dockerfile` | No hay programador de avisos. El entrypoint de la imagen ejecuta migraciones y arranca FastAPI, por lo que el worker necesita un entrypoint propio. |
| `restart_interview()` | `/interview` elimina perfil, historial y planes. No debe usarse para actualizar disponibilidad o preferencias en una revision, porque destruiria el contexto anterior. |
| Tests y documentacion | Hay pruebas de generacion, versionado, RAG, consultas sin mutacion, trazas y cuotas. La documentacion actual describe la regeneracion inmediata y las sustituciones como no implementadas. |

## Alcance y limites

Incluido: fechas del ciclo, cierre declarado, revision conversacional persistida, perfil
efectivo para entrenamiento, borradores aceptables/rechazables, versiones, alternativas
RAG, avisos, cuotas, trazabilidad, migracion y pruebas.

Fuera: diario de cargas/repeticiones por serie, deteccion objetiva de sesiones ejecutadas,
nutricionista, cambios en la duracion de cuatro semanas, reentrenamiento de embeddings,
diagnosticos, recomendaciones medicas y sustituciones automaticas sin consentimiento.
`/progress` se habilita solo para estado/cierre/revision del mesociclo, no como seguimiento
completo del rendimiento.

## Arquitectura propuesta

### 1. Separar ciclo, version y flujo pendiente

Mantener el JSON `TrainingPlan` compatible y las versiones existentes:

- `training_mesocycles`: chat, estado, inicio, fin previsto, cierre confirmado y relacion
  con el ciclo anterior. Fechas en UTC. La duracion prevista son 28 dias desde el inicio
  confirmado; no desde la generacion del borrador.
- `training_plans`: conservar payloads inmutables. Anadir `mesocycle_id`,
  `parent_plan_id`, tipo de cambio (`initial`, `renewal`, `exercise_swap`) y procedencia
  del contexto de generacion. Una version se asigna al aceptar, no al crear un borrador.
- `training_workflows`: flujo persistido de revision o sustitucion, plan base, ciclo base,
  estado, datos pendientes, revision validada, perfil efectivo, candidatos recuperados,
  borrador y sus trazas. Una restriccion permite como maximo un flujo abierto por chat.
  Conservar los flujos cerrados como evidencia de decisiones y aprobaciones.
- `training_notifications`: eventos pendientes con clave unica de ciclo/tipo/ocasion,
  fecha de entrega, destino, intentos, estado y lease de procesamiento. Posponer programa
  una nueva ocasion explicita; repetir una comprobacion no crea otro aviso.
- `training_sessions.current_plan_id` sigue siendo la autoridad del plan vigente.
  Mantener `status=active` durante revisiones: un flujo pendiente no rompe consultas.

Estados del flujo: `reviewing`, `generating`, `awaiting_confirmation`, `accepted`,
`cancelled`, `stale`. Los estados de ciclo distinguen activo y cierre confirmado.
Llegar a la fecha prevista no es una transicion a completado.

El repositorio obtiene el vigente por el puntero de sesion y propiedad del chat.
Usar operaciones tipadas de repositorio para iniciar flujo, guardar progreso/borrador,
aceptar, cancelar, cerrar ciclo y coordinar avisos; no exponer mutaciones arbitrarias.
Separar en un repositorio de entrenamiento los nuevos metodos si evita ampliar el
repositorio conversacional con todas las operaciones del ciclo.

### 2. Deteccion y revision

La misma politica de dominio se llama desde el bot y desde el worker:

1. Consultar el ciclo vigente, su fin previsto, preferencias y un posible flujo abierto.
2. Si vence, proponer revision sin afirmar que el usuario ha completado las sesiones.
3. Si el usuario declara que termino antes, permitir iniciar el cierre sin esperar la fecha.
4. Si no termino, conservar el plan y recoger nueva fecha prevista o posposicion.
5. Confirmado el cierre, registrar ese hecho e iniciar una revision breve reanudable.

Revision estructurada y conversacional, con preguntas agrupadas y sin repetir respuestas:

- Adherencia aproximada: sesiones realizadas frente a previstas, o desconocido.
- Evolucion declarada: mejoras, estancamientos y dificultades; resultados concretos si existen.
- Fatiga y recuperacion, sueno y percepcion de esfuerzo.
- Molestias/restricciones nuevas; respuestas que exijan detener la actividad y derivar.
- Ejercicios que quiere mantener/cambiar y motivo: material, preferencia o dificultad.
- Cambios de objetivo, dias, minutos, entorno y equipamiento.

Campos desconocidos se mantienen como tales; no imputar sesiones, cargas ni progresos.
Separar siempre rendimiento prescrito y resultados autodeclarados.
Validar parches de perfil por una lista explicita de campos de entrenamiento.
Guardar un contexto efectivo para entrenamiento con las actualizaciones confirmadas y
su procedencia; reutilizarlo en futuras consultas y ciclos sin alterar el informe original
del entrevistador ni recalcular datos ajenos al entrenamiento.
Una modificacion posterior de restricciones invalida un borrador que ya no sea compatible.

### 3. Generar el siguiente mesociclo

Crear un contrato `TrainingAdaptationContext` que incluya:

- Perfil efectivo y restricciones actuales.
- Plan base completo, ids/version/ciclo y fecha de cierre.
- Resumen determinista del plan: series por target y semana, dias, RPE, tiempos,
  ejercicios principales y descarga. Reutilizar o extraer funciones del evaluador.
- Revision autodeclarada, incertidumbres, preferencias y sustituciones solicitadas.
- Catalogo actualizado: ejercicios previos recuperados por id mas candidatos RAG validos.

No sumar versiones como si fueran ciclos distintos. El ultimo plan confirmado del ciclo
es la base, y las sustituciones dentro del ciclo quedan explicadas por su linaje.
Recuperar por id para conservar ejercicios utiles aunque no entren en el nuevo top-k.
Si un id anterior desaparece, no inventar metadatos: buscar alternativas validas e informar.

Anadir `generate_next_plan(context, exercises)` sin cambiar el contrato del primer plan.
Usar instrucciones especificas de renovacion y esquema estricto, manteniendo los datos
separados de las instrucciones y sin meter todo el historial de chat.

Politica de adaptacion explicita:

- Buena adherencia, mejora y recuperacion: conservar ejercicios principales y progresar
  de forma gradual dentro de limites del perfil; no cambiar todo para crear novedad.
- Adherencia baja: simplificar o ajustar calendario y duracion antes de aumentar volumen.
- Fatiga alta: mantener/reducir estimulo y priorizar recuperacion.
- Estancamiento: revisar adherencia/esfuerzo y variar lo justificado, no aumentar siempre.
- Dolor nuevo o restricciones preocupantes: detener la actividad afectada y recomendar
  evaluacion profesional; no presentar una variacion como tratamiento.
- Datos insuficientes: mantener una base conservadora y explicar incertidumbre.

No inferir kilos ni incrementos de carga no registrados. El contrato actual permite
series/repeticiones/RPE y notas de progresion. No prometer mejoria garantizada.
La nueva semana 1 toma como referencia el trabajo tolerado en semanas 1-3 y la revision,
no el volumen bajo de la descarga de semana 4.
Conservar la periodizacion de cuatro semanas y los techos de seguridad existentes.

Devolver borrador y resumen de diferencias/motivos vinculados a evidencia. Guardarlos
antes de anunciar que estan disponibles. Mostrar que aun no son el plan vigente.
Reutilizar validacion de ids y reparacion unica. Extraer reglas deterministas fiables
del evaluador para validacion de este flujo; las heuristicas se muestran como advertencias
o motivan aclaracion, no se convierten en una supuesta certificacion de seguridad.

### 4. Sustituciones con RAG

Resolver primero el ejercicio en el plan vigente: si el nombre o sus ocurrencias son
ambiguos, preguntar. Recoger motivo, semana actual y alcance; no deducir ejecucion
real solo de los dias transcurridos.

Ampliar `ExerciseRepository` con lectura por ids y busqueda filtrada de alternativas:

- Grupo muscular explicito como condicion, no solo en el embedding.
- Priorizar mismo target; no considerar biceps y triceps equivalentes por pertenecer a arms.
- Excluir el ejercicio origen y candidatos incompatibles con restricciones confirmadas.
- Filtrar material por disponibilidad real, normalizando aliases conocidos.
  Si la disponibilidad es ambigua, preguntar antes de ofrecer un ejercicio que requiera material.
- Usar instrucciones y metadatos disponibles para comparar el movimiento. Si faltan
  metadatos de equivalencia o seguridad, no afirmar una equivalencia exacta.
- Ordenar semanticamente dentro del conjunto elegible y limitar resultados.
- Compartir la agrupacion de targets ya existente en el evaluador cuando falte
  `muscle_group`; si no puede determinarse el grupo, no aceptar una sustitucion no validada.

No modificar corpus ni embeddings. Las tablas vectoriales siguen siendo de solo lectura
y no reciben migraciones Alembic de la base de aplicacion.
La extension de filtros sera opcional para preservar la recuperacion del primer plan.

Proponer hasta tres opciones, segun disponibilidad, con ids reales, nombres canonicos,
motivo y ajustes de prescripcion cuando correspondan. El LLM devuelve un contrato
especifico de propuesta; el backend comprueba pertenencia a candidatos y grupo/target.
Sin alternativas adecuadas: informar y mantener el plan, sin completar desde memoria.

Tras seleccionar y confirmar, el backend aplica un parche limitado a slots autorizados,
valida el plan resultante y crea una version del mismo ciclo. No permitir que el LLM
reescriba arbitrariamente el resto del bloque. Las ocurrencias anteriores no cambian.
Validar volumen, tiempo, duplicados y parametros de prescripcion; no trasladar sin
revision las mismas repeticiones a movimientos de naturaleza distinta.
En una renovacion pendiente, actualizar preferencias/borrador y solicitar de nuevo
confirmacion sin activar versiones intermedias.

### 5. Conversacion y activacion

Extraer la orquestacion de ciclo/revision/sustitucion a un servicio de entrenamiento.
`ConversationService` conserva transporte, rutas generales y manejo de errores.

- `/train` sin plan: conserva generacion y activacion inicial.
- `/train` con plan: inicia o reanuda revision/renovacion; deja de regenerar y activar
  silenciosamente. Mostrar el cambio de comportamiento en mensajes y documentacion.
- `/progress`: estado del ciclo y acceso a cierre/revision, sin diario.
- Subacciones explicitas de `/train` para confirmar, cancelar, cambiar y controlar
  avisos, con identificador de propuesta para evitar confirmar un borrador distinto.
- Mensajes libres ordinarios siguen en consulta de solo lectura, sin RAG.
  Anadir deteccion tipada de solicitud de revision/sustitucion; solo enruta o pregunta,
  nunca autoriza una mutacion. Reutilizar la llamada de consulta cuando sea viable
  para no clasificar cada mensaje mediante una segunda llamada al modelo.
- Durante un flujo, respuestas alimentan ese flujo; consultas separadas deben seguir
  pudiendo responderse sin mezclarse con datos de revision.
- Controles textuales en esta entrega: no introducir callbacks de Telegram, actualmente
  excluidos de `allowed_updates`, salvo que se cambie explicitamente ese alcance.

Aceptar un borrador en una transaccion bajo lock por chat:

1. Verificar identidad, estado pendiente, plan base aun vigente y contexto compatible.
2. Asignar version N+1 e insertar payload/report/trazas.
3. En renovacion, abrir nuevo ciclo con inicio confirmado y marcar el anterior
   reemplazado/cerrado segun su estado; en sustitucion, conservar ciclo y fechas.
4. Actualizar puntero de sesion y cerrar flujo.
5. Registrar confirmacion; despues comunicar exito a Telegram.

Confirmaciones repetidas son idempotentes y no crean otra version. Una propuesta obsoleta
se marca `stale` y requiere regenerar, nunca se activa sobre otro plan.
Reservar la generacion en el flujo con lease antes de la llamada externa; no mantener
una transaccion ni un lock abiertos durante el LLM. Evitar llamadas duplicadas concurrentes
y permitir recuperar flujos interrumpidos sin activar contenido parcial.
No bloquear rechazos, confirmaciones ni posposiciones por una cuota de LLM agotada.
Aplicar cuotas por accion: generacion/renovacion/sustitucion costosa con nivel soft,
consulta con hard, controles deterministas y avisos sin consumo.
Preservar deduplicacion de updates, replies al thread, limpieza de texto y webhook 2xx.

### 6. Worker de avisos

Worker ejecutable con `python -m fitcoach.infrastructure.jobs.training_reminders`.
Reutilizar bot, configuracion y politica de deteccion; sesiones de DB propias por lote.
Implementar ejecucion unica y bucle periodico con apagado limpio, sin dependencias nuevas.

- Comprobar ciclos vencidos, preferencias y flujos abiertos; no llamar al LLM.
- Crear/reservar eventos atomicos compartidos con la deteccion al conversar.
- Usar leases y bloqueo de filas para varios workers, reinicios y procesos concurrentes.
- No enviar si el ciclo ya cambio, fue pospuesto, se desactivaron avisos o existe revision.
- Guardar destino/thread conocido y no exponer informacion en otro chat.
- RetryAfter y fallos transitorios: reprogramacion acotada y visible en logs.
  Chat bloqueado/no disponible: estado explicito, sin bucle infinito.
- Un unico aviso inicial salvo posposicion explicita. Opt-out disponible.

Telegram no ofrece una transaccion conjunta con PostgreSQL: documentar entrega al menos
una vez y la posibilidad residual de duplicado si el proceso cae despues de enviar y
antes de confirmar entrega. La coordinacion evita duplicados normales, no promete
exactly-once externo.

Agregar servicio worker en composiciones relevantes de dev/local/prod y pruebas;
sobrescribir el entrypoint de la imagen para no arrancar FastAPI ni ejecutar migraciones
concurrentes. Esperar esquema listo y fallar claramente si no lo esta.
Anadir configuracion con valores por defecto y un flag de despliegue para habilitar
avisos controladamente; actualizar `.env.example` y documentacion de despliegue.

### 7. Compatibilidad y migracion

- Migracion aditiva Alembic, preservando ids, versiones, payloads e informes.
- Asociar planes antiguos a ciclos legacy separados: antes cada generacion era independiente.
  No reconstruir resultados ni finales realizados a partir de `created_at`.
- Respetar el puntero actual de sesion. Detectar inconsistencias y registrarlas;
  no sustituirlo silenciosamente por la mayor version.
- Para el vigente legacy, pedir fecha de inicio o confirmacion de que termino en la
  proxima interaccion. Hasta resolverlo no enviar avisos masivos por antiguedad.
- Configurar ciclos nuevos con fechas desde activacion; cambiar ejercicios nunca las reinicia.
- Adaptar el reset de entrevista al nuevo grafo: cancelar flujos/avisos y limpiar los
  datos dependientes de forma transaccional conforme a la semantica actual del reset.
- Actualizaciones breves de perfil no llaman al reset de entrevista.
- Primer plan y consultas normales mantienen contratos, trazas y comportamiento existentes.
- Sin dependencias nuevas previstas. Si fueran necesarias, cambiar `pyproject.toml` y
  regenerar ambos requirements compilados, nunca editarlos manualmente.

## Todos y dependencias

| ID | Trabajo | Depende de |
| --- | --- | --- |
| training-contracts | Modelos de ciclo, revision, contexto adaptativo, propuestas y politica de deteccion; invariantes y pruebas unitarias. | — |
| training-persistence | Migracion, modelos SQL, repositorio, flujos, locks/leases, activacion y compatibilidad legacy. | training-contracts |
| exercise-alternatives | Lectura de catalogo por ids, filtros de alternativas, normalizacion compartida y pruebas RAG. | training-contracts |
| trainer-adaptation | Cadena/prompts de renovacion y sustitucion, resumen y validadores reutilizados, casos de evaluacion. | training-contracts, exercise-alternatives |
| training-conversation | Integrar revision, controles, sustituciones y consultas en Telegram; cuotas por accion y mensajes. | training-persistence, trainer-adaptation |
| training-reminders | Worker y eventos de avisos coordinados, preferencias, errores y apagado. | training-persistence |
| training-deployment-docs | Composiciones/entrypoint/configuracion y documentacion del nuevo comportamiento. | training-conversation, training-reminders |
| training-validation | Pruebas end-to-end, concurrencia/migracion, calidad y cobertura global. | training-conversation, training-reminders, training-deployment-docs |

## Validacion y criterios de aceptacion

Pruebas unitarias con reloj inyectable, AsyncMock y esquemas estrictos:

- Un ciclo no vence antes de 28 dias; justo al alcanzar el limite propone revision.
- Vencimiento no equivale a cierre; closure declarado, posposicion y opt-out.
- Revision reanudable, respuestas desconocidas, parches permitidos y casos de riesgo.
- Contexto de renovacion incluye perfil efectivo, plan anterior y revision.
- No usar la descarga como baseline ni interpretar prescripcion como ejecucion.
- Buena adherencia, fatiga, estancamiento y datos insuficientes en casos golden
  estructurados, sin depender de comparar texto libre.
- Lectura por ids, grupo/target/material, exclusion origen, candidato inexistente,
  metadatos insuficientes, ausencia de alternativas y fallos de embedder/pgVector.
- Consulta normal no usa RAG ni modifica plan.
- Cambios solo en slots confirmados, sin duplicados, manteniendo ciclo/fechas.
- Fallos del modelo y reparacion unica no dejan planes activos parciales.
- Cuotas por accion y controles sin LLM aunque se haya agotado la cuota.

Integracion con PostgreSQL/pgVector reales y stubs existentes:

- Migracion desde datos legacy sin perdida ni avisos inesperados.
- Borrador generado: puntero y version activa intactos.
- Confirmacion: exactamente una nueva version; renovacion abre ciclo y sustitucion no.
- Cancelacion: ningun plan nuevo activo; doble confirmacion no duplica.
- Dos peticiones concurrentes, webhook repetido y worker simultaneo con interaccion.
- Plan/contexto base modificado durante generacion: borrador obsoleto no se activa.
- Worker reiniciado, lease vencido, fallo de Telegram y cancelacion de evento obsoleto.
- Reset de entrevista elimina/cancela dependencias y evita avisos posteriores.
- Usar el cliente IT autenticado existente y ampliar fixtures/stub_server sin llamadas reales al LLM.

Ejecutar primero pruebas dirigidas. Al cerrar la implementacion:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest tests --cov=src/fitcoach --cov-fail-under=80
```

Preparar los contenedores de integracion segun los targets existentes (`make tests`
cuando sea el camino completo), no confundir una suite sin infraestructura con una
validacion satisfactoria. Comprobar arranque y respuesta del worker en su composicion.

Actualizar `docs/trainer-agent.md`, `docs/modelo-datos.md`, `docs/rate-limiter.md`,
documentacion de despliegue y README en los apartados afectados. Sin cambiar reglas
de tooling ajenas a esta funcionalidad.

## Riesgos que deben permanecer explicitos

Sin diario, el cierre y los resultados son autodeclarados. Los metadatos del corpus no
garantizan equivalencia biomecanica ni seguridad clinica. No sustituir esa incertidumbre
por recomendaciones inventadas. La actualizacion del perfil y la revision deben quedar
asociadas al borrador para poder explicar por que se propone cada cambio.
El despliegue debe habilitar avisos despues de migrar y sin una avalancha a usuarios legacy.
