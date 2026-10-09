# Plan de evaluación y adopción de LangChain Agents y LangGraph

> Estado: propuesta para una decisión futura, no implementación aprobada.
> Fecha de análisis: 9 de octubre de 2026.
> Este documento no modifica el comportamiento de FitCoachIA ni incorpora dependencias.

## 1. Conclusión y recomendación

Es viable incorporar `langchain.agents.create_agent` y LangGraph sin reescribir la aplicación.
Son herramientas complementarias, no alternativas excluyentes: los agentes de LangChain se
apoyan en LangGraph, mientras que LangGraph también puede orquestar nuestras cadenas actuales
sin usar `create_agent`.

La recomendación es una adopción **híbrida, incremental y condicionada a resultados**:

1. Mantener la entrevista y la generación de planes como flujos controlados.
2. Evaluar `create_agent` en consultas del entrenador con herramientas de solo lectura.
3. Evaluar LangGraph cuando haya una necesidad concreta de coordinación, ramificación o
   reanudación entre especialistas.
4. Con entrevistador, entrenador, nutricionista y coach disponibles, utilizar un enrutador
   controlado y activar únicamente los especialistas necesarios para cada consulta.

Tener cuatro roles no obliga a adoptar LangGraph ni a invocar cuatro modelos por mensaje.
Tampoco garantiza que un supervisor LLM mejore un enrutador escrito en Python.
La opción de conservar la arquitectura actual debe permanecer en la comparación.

## 2. Situación real del repositorio

| Elemento | Situación comprobada |
| --- | --- |
| Dependencias declaradas | `langchain-core>=1.2.17` y `langchain-openai>=1.1.11` en `pyproject.toml`. |
| Versiones resueltas | `langchain-core==1.6.2` y `langchain-openai==1.6.0` en `src/requirements.txt`. No demuestra qué versión está instalada en cada despliegue. |
| API de agentes | No hay uso de `langchain.agents`, `create_agent` ni `AgentExecutor` en el código de la aplicación revisado. |
| LangGraph | No está declarado ni utilizado en la aplicación revisada. |
| Entrevistador | `InterviewerChain` compone mensajes e invoca un modelo mediante `BaseLLMChain`. |
| Entrenador | `TrainerChain` genera y valida planes; consulta, renovación y sustitución tienen flujos diferenciados. |
| Recuperación | `ExerciseRetriever` aplica búsquedas por target/material; la recuperación de generación está controlada por código. |
| Consultas actuales | Usan el plan guardado, perfil efectivo e historial; no hacen RAG ni modifican el plan por sí mismas. |
| Nutricionista y coach | `AgentType` reserva sus identificadores, pero no existen implementaciones de esos agentes. |
| Curador de ejercicios | Ya existe `ExerciseCuratorAgent`; es una capacidad adicional, no uno de los cuatro roles principales ni motivo para eliminar la moderación. |

`BaseLLMChain` ya aporta contabilización de tokens, traducción de errores, validación Pydantic
y una reparación de salida inválida. El entrenador añade restricciones que no se resuelven
solo con un esquema JSON: IDs reales, equipamiento, coherencia con el perfil y reglas del plan.

Referencias del código: `src/fitcoach/service/agent/llm_chain.py`,
`src/fitcoach/service/agent/interviewer_chain.py`,
`src/fitcoach/service/agent/trainer_chain.py`,
`src/fitcoach/service/agent/exercise_retriever.py`,
`src/fitcoach/service/conversation_service.py` y `src/fitcoach/domain/agents.py`.
Comportamiento vigente: [entrevistador](../interviewer-agent.md),
[entrenador](../trainer-agent.md) y [scheduler](../scheduler.md).
Los planes históricos de `docs/plan/` no sustituyen esas referencias del estado actual.

## 3. Qué aporta cada tecnología

### LangChain Agents: selección de herramientas dentro de una tarea

`create_agent` ofrece un bucle modelo → herramientas → modelo. Se configura con un modelo,
herramientas, prompt y, cuando procede, un contrato de salida estructurada.
Permite añadir middleware para intervenir en la ejecución.

Su ventaja principal aquí sería que el entrenador pudiera decidir si necesita consultar
ejercicios o evaluaciones para contestar, en lugar de recibir siempre el mismo contexto.
Una segunda búsqueda podría depender del resultado de la primera.

La salida estructurada puede usar capacidades nativas del proveedor o herramientas.
Un endpoint compatible con OpenAI no garantiza soporte de tool calling, ni soporte simultáneo
de herramientas y salida estructurada. Debe comprobarse con el modelo y proveedor elegidos.
La validación estructural no sustituye las restricciones de dominio.

Si el único objetivo fuera mejorar el JSON, hay una alternativa menor: evaluar la salida
estructurada directamente sobre `ChatOpenAI`, sin incorporar un bucle de agente.

### LangGraph: coordinación explícita y estado de ejecución

LangGraph permite representar pasos, condiciones, ciclos y ramas paralelas mediante un grafo.
Cada nodo puede ser una función determinista, una cadena existente o un agente con herramientas.
No exige que todos los nodos sean LLM ni que se reemplace `BaseLLMChain`.

Con un checkpointer persistente permite guardar el estado de ejecución, reanudar flujos e
introducir interrupciones para intervención humana. Son capacidades que requieren diseño,
almacenamiento y pruebas: no se obtienen simplemente por dibujar un grafo.

Un checkpoint no sustituye el perfil, plan, historial o transacción de negocio de PostgreSQL.
Tampoco proporciona por sí solo entrega exactamente una vez de mensajes o cambios de plan.
LangSmith y los servicios alojados son opcionales; no se propone activarlos ni enviarles
datos personales. Se conservaría nuestra observabilidad OpenTelemetry.

## 4. Comparación y valoración

| Alternativa | Beneficio principal | Coste o riesgo | Valoración para FitCoachIA |
| --- | --- | --- | --- |
| Cadenas y servicios actuales | Control explícito, llamadas acotadas y reglas ya implementadas. | Coordinación compleja escrita a mano si crecen las ramas. | Adecuada para entrevista, generación y confirmaciones actuales. |
| `create_agent` solo en consultas | Selección flexible de herramientas y búsquedas sucesivas. | Más llamadas posibles, latencia y dependencia de capacidades del proveedor. | Buen candidato para una prueba de solo lectura. |
| LangGraph con cadenas existentes | Flujo visible, ramas y reanudación sin convertir todo en autónomo. | Nuevo runtime y, si hay checkpoints, operación y persistencia adicionales. | Interesante cuando la complejidad real de coordinación lo justifique. |
| LangGraph con agentes en algunos nodos | Control global y flexibilidad local. | Mayor superficie de pruebas, límites y contabilización. | Objetivo futuro preferido si las evaluaciones justifican ambos niveles. |
| Supervisor LLM que delega siempre | Coordinación dinámica entre especialistas. | Llamadas extra, contexto duplicado y delegaciones incorrectas. | No recomendado como primera implementación. |

No se esperan automáticamente mejores planes, menos alucinaciones, menor consumo ni mayor
velocidad. Paralelizar reduce parte del tiempo de espera solo si las tareas son independientes;
no elimina sus tokens ni garantiza resultados compatibles.

## 5. Utilidad cuando existan los cuatro agentes

### Responsabilidades y límites propuestos

| Rol | Responsabilidad futura | Contexto mínimo | Límites |
| --- | --- | --- | --- |
| Entrevistador | Recopilar y aclarar datos para un perfil validado. | Respuestas y campos necesarios para la entrevista. | No cambia por su cuenta planes vigentes ni inventa datos ausentes. |
| Entrenador | Planificar entrenamiento y responder sobre ejercicios y progresión. | Perfil efectivo, plan, registros pertinentes y catálogo autorizado. | No prescribe nutrición clínica ni activa cambios sin autorización. |
| Nutricionista | Orientación alimentaria dentro del alcance que se apruebe. | Objetivos, actividad, preferencias y restricciones pertinentes. | Su contrato, fuentes y límites clínicos aún deben definirse; no asumir prescripción o suplementación automática. |
| Coach | Apoyo conductual y organización de hábitos. | Objetivos aceptados, compromisos y seguimiento necesario. | No diagnostica, no promete resultados ni modifica planes de otros roles. |

Un perfil validado puede ser compartido por referencia y versión, pero no se debe copiar el
historial completo a todos los prompts. Cada especialista recibe una proyección mínima y
autorizada. Los datos desconocidos y la incertidumbre conservan esa condición.

### Casos donde la coordinación sí aporta valor

- **Inicio:** el entrevistador completa el perfil; después se habilitan las capacidades
  aprobadas. Entrenamiento y nutrición podrían generar propuestas en paralelo solo si sus
  contratos no requieren el resultado del otro.
- **Consulta transversal:** ante «he cambiado mis horarios, ¿cómo organizo entrenamiento y
  comidas?», se solicitan respuestas a los especialistas pertinentes y se presenta una
  propuesta compatible. No se activan cambios por haber expresado una intención.
- **Seguimiento:** registros y evaluaciones seleccionados sirven para proponer ajustes;
  el coach ayuda con hábitos sin interpretar ausencia de registro como incumplimiento.
- **Conflictos:** si dos propuestas discrepan sobre carga, recuperación u objetivos, se
  detecta el conflicto y se pide aclaración o revisión limitada. No se deja un debate infinito
  entre modelos ni se permite que una síntesis borre restricciones de seguridad.

Las comprobaciones de compatibilidad deben ser deterministas donde sea posible. Las reglas
clínicas y los límites de cada rol requieren definición profesional, no generación automática
por otro LLM.

### Patrones de coordinación a considerar

| Patrón | Aplicación | Decisión propuesta |
| --- | --- | --- |
| Router | Comandos/estado seleccionan un especialista; una clasificación acotada interpreta mensajes ambiguos. | Empezar por reglas; preguntar si la intención es incierta. No llamar a todos por defecto. |
| Handoffs | Cambiar el interlocutor activo durante una conversación especializada. | Solo transiciones permitidas y persistidas; distinguir selección de rol de autorización de cambios. |
| Subagentes como herramientas | Un coordinador consulta especialistas para una pregunta transversal. | Evaluar después del router, con profundidad y número de delegaciones limitados. |
| Workflow personalizado | Coordinar validación, especialistas, conflictos, propuesta y confirmación. | Patrón preferido para un grafo híbrido. |
| Un modelo con skills | Cargar conocimientos según la tarea sin agentes separados. | Alternativa si los roles no necesitan modelos, herramientas o estados diferentes. |

Estas skills de ejecución no son la skill de documentación de desarrolladores
`.claude/skills/langchain-docs/SKILL.md`.

## 6. Arquitectura futura propuesta

```text
Webhook / callbacks / Mini App
    → autenticación y contexto autorizado
    → servicio de conversación: comandos, cuota y estado actual
    → orquestador de aplicación
        → ruta determinista o aclaración de intención
        → cadenas actuales / especialistas / agente de consulta con herramientas
        → validaciones de dominio y detección de conflictos
        → respuesta de lectura o borrador pendiente
    → servicios y repositorios existentes
    → entrega mediante el bot
```

El grafo, si se adopta, coordina el flujo dentro del monolito; no se propone un servicio externo
ni sustituir el scheduler. Los nodos usan puertos y servicios, no SQL libre generado por el LLM.
Los tipos de LangChain/LangGraph quedan fuera de `domain/` y de los contratos de repositorio.
El wiring permanece en los puntos de composición actuales.

Esquema conceptual para solicitudes transversales, no código listo para ejecutar:

```text
autorizar → cargar contexto/versiones → seleccionar capacidades
    ├─ datos insuficientes → pedir aclaración → terminar o pausar
    ├─ consulta simple → especialista → validar respuesta → responder
    └─ propuesta transversal → especialistas necesarios
          → validar contratos y compatibilidad
          → aclaración si hay conflicto
          → guardar borrador → esperar confirmación
          → revalidar propietario/versiones → activar mediante servicios
```

La entrevista y las consultas de lectura no necesitan recorrer todos esos pasos.

## 7. Estado, permisos y consistencia

El estado conceptual incluiría `workflow_id`, propietario autorizado, intención, agente activo,
referencias/versiones de perfil y planes, resultados tipados, estado de propuesta, presupuesto
consumido y siguiente acción. No incluiría secretos, clientes HTTP, sesiones SQLAlchemy ni
repositorios: se inyectan en el contexto de ejecución.

La identidad y las versiones se cargan desde la aplicación, no desde argumentos del modelo.
Las herramientas iniciales serían, por ejemplo, `get_current_plan`, `get_evaluation_summary`
y `search_exercises`, con resultados acotados. Una búsqueda respeta siempre las restricciones
del perfil aunque el modelo solicite ampliarlas. Sin resultados se devuelve un estado explícito.

El identificador de thread de LangGraph es un identificador interno de workflow ligado al chat
y propietario; no equivale a `message_thread_id` de Telegram. Conocerlo no concede permisos.
Las ejecuciones sobre el mismo flujo necesitan control de concurrencia y versión.

PostgreSQL conserva la verdad de negocio; los checkpoints almacenan estado de ejecución.
Se define retención, borrado, acceso y minimización de datos sensibles antes de persistirlos.
Reiniciar `/interview`, invalidar un perfil o cambiar un plan debe cancelar o invalidar también
los workflows/checkpoints afectados.

Una interrupción devuelve el control al handler; no mantiene un webhook abierto esperando
al usuario. La reanudación llega en otro update autorizado y valida la revisión de la propuesta.
Los nodos con `interrupt()` pueden volver a ejecutarse desde su inicio al reanudar: no situar
efectos no idempotentes antes de esa pausa.

Checkpoints, commits de negocio y envío a Telegram no forman automáticamente una transacción
atómica. Se necesitan claves de idempotencia, comprobación de versiones y una estrategia
explícita para recuperarse de fallos entre esos pasos. Evaluar reutilizar la cola existente
para entrega diferida si el caso lo necesita; no asumir entrega exactamente una vez.
El webhook conserva el contrato actual de respuesta ante updates válidos y errores manejados.

## 8. Coste, seguridad y observabilidad

Antes de activar un bucle se fijan máximos aprobados de llamadas LLM, herramientas, delegaciones,
reparaciones, tiempo y tokens. El límite de recursión del grafo no sustituye esos presupuestos.
Se comprueba el presupuesto antes de cada nueva llamada y se contabiliza su consumo real;
no se promete un techo exacto a partir de una comprobación previa.

Las tareas paralelas necesitan reserva o coordinación del presupuesto compartido para evitar
que cada rama consuma como si fuera la única. El histórico de cuota no basta por sí solo para
controlar llamadas simultáneas.

Debe registrarse cada llamada facturable una sola vez, incluidas clasificación, síntesis,
reparación y fallos con consumo conocido. No volver a contar mensajes históricos que aparezcan
en el estado reanudado. Si se desconoce el consumo, conservar la distinción según el patrón
actual, sin inventar cifras.

La primera prueba no admite herramientas de escritura, SQL arbitrario, ejecución de comandos
ni accesos externos nuevos. Los textos recuperados se tratan como datos no confiables.
Persistencia, moderación, confirmaciones y reglas de seguridad permanecen bajo control de
los servicios, no de las instrucciones del prompt.

OpenTelemetry y logs conservarían contexto de update/chat, fase, especialista, llamada y
workflow, evitando contenido personal en atributos. Se medirían latencia p50/p95, llamadas,
tokens/coste, fallos, reparaciones, calidad de herramientas y bloqueos por validación.
No se activaría LangSmith ni otro envío de trazas externas sin una decisión específica.

## 9. Plan de implementación por fases

Cada fase requiere aprobación propia. Documentar esta propuesta no autoriza ejecutarlas.

| Fase | Trabajo | Dependencias reales | Criterio para continuar |
| --- | --- | --- | --- |
| 0. Línea base | Preparar consultas representativas y medir las cadenas actuales. Definir presupuestos y criterios comparativos. | Fixtures/evaluación y decisión del desarrollador; sin nueva dependencia obligatoria. | Casos y umbrales aceptados antes de evaluar alternativas. |
| 1. Compatibilidad | Resolver versiones candidatas y probar `create_agent` con el proveedor/modelo elegido: herramientas, async y salida estructurada. | `langchain` como runtime si se aprueba; regenerar ambos requirements, docs y fixtures. | Happy path y fallos soportados; estrategia explícita para el proveedor, sin cambios silenciosos. |
| 2. Consulta de lectura | Introducir un adaptador de agente y herramientas autorizadas para consultas del entrenador, sin alterar la generación. | Fase 1; integración de cuota/consumo, pruebas unitarias e IT y activación reversible. | Mejora útil sin regresiones de aislamiento, seguridad, coste o latencia fuera de los umbrales. |
| 3. Grafo acotado | Comparar router/workflow Python con LangGraph, reutilizando cadenas. Añadir checkpoints solo si la reanudación es necesaria. | Línea base; `langgraph` runtime si se importa directamente; adapter de checkpoints y schema solo si procede. La fase 2 no es obligatoria para un grafo sin agentes. | Beneficio demostrado frente a servicios normales; recuperación y consistencia verificadas. |
| 4. Cuatro especialistas | Incorporar contratos de nutricionista/coach y coordinar una consulta transversal mediante capacidades disponibles. | Implementación y aprobación independiente de esos roles, sus fuentes, límites y pruebas; fases evaluadas pertinentes. | Conflictos, contexto mínimo y autorizaciones controlados; no activaciones automáticas. |
| 5. Despliegue gradual | Habilitar capacidades seleccionadas, vigilar métricas y permitir desactivación. | Pruebas completas, documentación operativa y política de workflows abiertos. | Reversión y atención de ejecuciones pendientes probadas. |

La fase de cuatro especialistas no es un atajo para construir nutricionista y coach:
cada uno necesita sus propios contratos, prompts, configuración, persistencia necesaria,
tests OK/KO y documentación, según `AGENTS.md`.

### Superficies que cambiarían si se aprueba implementar

| Superficie | Cambios previstos o condicionados |
| --- | --- |
| `service/agent/` y servicios | Adaptador de consulta, herramientas y, si procede, orquestación. Mantener resultados tipados y validadores existentes. |
| `api/webhook.py` / composición | Inyectar capacidades sin convertir endpoints en lógica de negocio. |
| `pyproject.toml` | Preguntar y aprobar grupos; runtime para librerías usadas en ejecución. Regenerar `src/requirements.txt` y `.github/requirements-ci.txt`, actualizar `docs/toml.md`. |
| Configuración | Solo límites y flags realmente necesarios, con validación fail-fast, `.env.example`, `docs/how-to.md` y composes afectados. No editar archivos de entorno reales. |
| DB / checkpoints | Si hay schema propio, modelos y Alembic. Si el backend crea tablas propias, aprobar antes su propiedad, setup, upgrades, permisos y compatibilidad con la política de migraciones. No ejecutar `setup()` indiscriminadamente al arrancar. |
| Tests / stub server | Respuestas de herramientas, fallos, salida estructurada y reanudación según la fase. |
| Documentación | Actualizar flujos vigentes, datos, observabilidad y despliegue; README/AGENTS si cambia el mapa. |
| Makefile / CI / contenedores | Solo si cambian comandos, servicios o checks; no añadir infraestructura alojada por defecto. |

No se fijan versiones nuevas ni nombres/valores de variables todavía. La resolución compatible
con Python y dependencias del proyecto es parte de la fase 1, no una compatibilidad asumida
por consultar la documentación más reciente.

## 10. Verificación y criterios de aceptación

| Área | Casos OK | Casos KO |
| --- | --- | --- |
| Herramientas | Consulta autorizada y resultado acotado; respuesta simple sin herramienta. | Chat ajeno, argumentos inválidos, herramienta no permitida, catálogo vacío y fallo de proveedor. |
| Dominio | Contratos válidos y ejercicios autorizados. | IDs inventados, equipamiento incompatible, salida inválida y cambios sin confirmación. |
| Presupuesto | Cada llamada nueva contabilizada, también en una respuesta transversal. | Cuota agotada, bucle sin fin, concurrencia que rebasa reservas y fallo con consumo conocido. |
| Grafo | Ruta correcta, aclaración, cancelación y reanudación después de reiniciar. | Checkpoint inaccesible/corrupto, esquema incompatible, doble callback y flujo invalidado por nueva entrevista. |
| Consistencia | Confirmación válida aplicada una vez. | Plan base cambiado, confirmación de otro usuario y caída entre checkpoint, commit y entrega. |
| Multiagente | Se invocan solo roles necesarios; conflictos detectados y desconocidos conservados. | Especialista no implementado/indisponible, respuestas contradictorias y fuga de contexto entre chats. |
| Transporte | Webhook y botones conservan contratos, propietario y thread de Telegram. | Fallo de envío, reinicio y callback obsoleto sin duplicar efectos ni afirmar éxito. |

Las pruebas unitarias mockean modelos, puertos y bots; las IT ejercitan el stub y los servicios
reales del compose de tests. La recuperación persistente requiere reiniciar el runtime:
una prueba con un saver en memoria no demuestra supervivencia al reinicio.

La evaluación compara calidad, coste total, latencia y cumplimiento de restricciones sobre
los mismos casos. Las nuevas herramientas no deben exponerse al grupo de control.
Los umbrales los aprueba el desarrollador; no declarar éxito solo por completar una demo.
Ejecutar los checks de calidad y `make tests` que exige el repositorio para la implementación.

## 11. Reversión y decisiones pendientes

La activación inicial debe permitir volver a la consulta actual sin ocultar errores.
Desactivar una capacidad no elimina checkpoints ni propuestas: decidir si se cancelan,
terminan con el runtime compatible anterior o migran explícitamente.
No reanudar un workflow persistido con un schema nuevo sin validar su compatibilidad.

Antes de implementar deben decidirse:

- Caso concreto de la prueba y expectativas de coste/latencia/calidad.
- Proveedor/modelo, estrategia de salida y versiones compatibles.
- Herramientas permitidas, límites y alcance de datos por especialista.
- Necesidad real de checkpoints frente a estado de workflow en repositorios existentes.
- Propiedad del schema, retención y autorización de reanudación.
- Alcance independiente del nutricionista y del coach.
- Flags de despliegue y tratamiento de ejecuciones abiertas durante rollback.

**Valoración final:** LangChain Agents aporta valor potencial en consultas con herramientas;
LangGraph aporta valor potencial en coordinación y continuidad complejas. La combinación
híbrida encaja mejor que una migración total, pero solo debe adoptarse tras demostrar que
resuelve un problema real mejor que las cadenas y servicios actuales.

## 12. Fuentes y alcance de la revisión

Documentación oficial consultada el 9 de octubre de 2026:

- [Índice para LLMs](https://docs.langchain.com/llms.txt) y
  [índice de Python](https://docs.langchain.com/_llms/agent-development-lifecycle/build/python.md).
- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents).
- [Salida estructurada](https://docs.langchain.com/oss/python/langchain/structured-output).
- [Patrones multiagente](https://docs.langchain.com/oss/python/langchain/multi-agent/index).
- [Workflow personalizado](https://docs.langchain.com/oss/python/langchain/multi-agent/custom-workflow).
- [LangGraph: visión general](https://docs.langchain.com/oss/python/langgraph/overview).
- [Persistencia](https://docs.langchain.com/oss/python/langgraph/persistence).
- [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers).
- [Interrupciones y reanudación](https://docs.langchain.com/oss/python/langgraph/interrupts).

Se contrastó documentación con código y dependencias declaradas/resueltas. No se instaló
`langchain` ni LangGraph, no se ejecutó un prototipo ni se verificaron capacidades del proveedor
real. Este análisis fundamenta una decisión; no acredita compatibilidad o mejoras medidas.
