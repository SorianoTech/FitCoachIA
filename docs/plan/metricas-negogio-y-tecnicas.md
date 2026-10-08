# Métricas de negocio y técnicas: dashboards independientes

Se implementan vistas de Grafana con **los datos ya disponibles**, sin modificar
reglas de negocio, flujos, tablas, eventos ni instrumentación de la aplicación.
El nombre de este fichero conserva la ruta original `metricas-negogio-y-tecnicas.md`.

## Organización

Los JSON viven en
`infra/observability/config/grafana/provisioning/dashboards/json/` y el proveedor
existente los carga en la carpeta **FitCoachIA**.

| Dashboard | UID | Tipo y fuentes |
|---|---|---|
| Negocio y activación | `fitcoach-business` | Cohortes actuales, adopción y coste conocido; PostgreSQL |
| Entrevistas | `fitcoach-interviews` | Proceso de entrevista y proxies de calidad; PostgreSQL/Loki |
| Telegram y backend | `fitcoach-telegram` | Actividad, descartes y eventos de fallo; Loki |
| Agentes y LLM | `fitcoach-agents` | Fiabilidad, tokens, coste y latencias; PostgreSQL/Loki |
| RAG y catálogo | `fitcoach-rag` | Recuperación y utilización de contexto; Loki/PostgreSQL |

El dashboard **Conversaciones** se conserva como vista previa/general para no
romper enlaces existentes. No se crea un dashboard vacío por cada KPI pendiente:
cada métrica implementable tiene panel propio en el dashboard de su tipo.

## Filtros y semántica comunes

- `environment=dev|prod` selecciona conjuntamente el datasource
  `fitcoach-postgres-${environment}` y el stream Loki del entorno.
- El rango de Grafana se aplica explícitamente a SQL y LogQL. El selector de
  agente solo afecta a los paneles SQL del dashboard Agentes; las fases Loki
  corresponden al entrenador y se identifican por acción/fase.
- Loki utiliza la etiqueta `environment` de Alloy/Docker, no el stream OTLP:
  evita contar dos ingestas del mismo log. Requiere Alloy y conserva 14 días.
  Un rango de 30 días en Loki puede ser parcial; ausencia de eventos no demuestra
  ausencia de actividad.
- Porcentajes sin denominador y costes completamente desconocidos quedan sin
  datos, no se transforman en cero. Los errores de datasource no se ocultan.
  Excepción: los paneles N4 muestran 0 junto a su recuento (ver N4).
- Ventanas LogQL de 24 horas son **móviles**, no días de calendario disjuntos.
  Los mensajes editados cuentan como updates; callbacks y duplicados no
  registrados como `update recibido` no forman parte del denominador.
- No se muestran contenido de mensajes, perfiles ni registros de salud.
  Los paneles no cambian permisos de Grafana; restringir el acceso a operadores.
- Las tablas de entrevista/perfil conservan el último intento. `/interview`
  elimina planes e historial previo: los indicadores describen datos
  actualmente conservados, no un histórico inmutable de todos los intentos.

## Negocio

| Métrica | Estado | Cálculo adaptado y límites |
|---|---|---|
| **N1. Entrevistas completadas** | Implementada | Cohorte con `started_at` dentro del rango: completadas / total. Caducidad estimada de `in_progress` con selector 7/14/30 días respecto a ahora, sin actualizar estado. No reconstruye intentos borrados. |
| **N2. Perfiles con plan** | Implementada | Perfiles con `completed_at` en rango y `EXISTS(training_plans)` / perfiles. No multiplica usuarios por versiones ni cuenta borradores pendientes. |
| **N3. Adopción de agentes** | Implementada | Media de agentes distintos por usuario con llamadas `success` en el rango (30 días por defecto); desglose de usuarios por agente. No incluye uso determinista de la Mini App. |
| **N4. Satisfacción del plan** | Implementada | Encuestas semanales de `training_evaluation`, cohorte por `sent_at`. Satisfacción = media de las medias por `chat_id` de las contestadas (cada cliente pesa igual). Sin contestar = `unanswered / (answered + unanswered)`; las `awaiting` quedan fuera. No generadas = jobs `evaluation_poll` `failed / (done + failed)` por `executed_at`; las `cancelled` no son fallos. **Excepción a la regla común**: sin datos muestran 0, y cada stat enseña su recuento (encuestas contestadas, cerradas o envíos intentados) para distinguir un 0 real de la falta de datos. Detalle por cliente en una fila plegable (`chat_id`, media, contestadas, sin contestar, abiertas); los clientes sin respuestas salen con media 0 al final. Confirmar un borrador sigue sin equivaler a satisfacción. |
| **N5a. Coste por plan generado** | Pendiente | Falta atribución persistida de llamadas/reparaciones a acción y evento de generación. `avg(cost_usd)` del trainer mide coste por llamada, no por plan; no se presenta como sustituto. |
| **N5b. Coste por usuario activado** | Proxy operativo | Coste LLM conocido del rango / usuarios distintos con un plan confirmado creado en ese rango, incluyendo versiones. Se muestra cobertura de precios. No es CAC, coste de cohorte causal ni cuenta exclusivamente primeros planes. |

## Telegram → backend

| Métrica | Estado | Cálculo adaptado y límites |
|---|---|---|
| **T1. Mensajes no procesables** | Implementada | Logs de descarte por falta de texto o emojis/espacios / `update recibido`. No es porcentaje de errores HTTP. |
| **T2. Entrantes y salientes** | Parcial | Entrantes observados en el rango, serie móvil de 24 h y media por usuario observado. Salientes pendientes: no existe evento fiable de entrega; mensajes de conversación no equivalen a mensajes Telegram enviados. |
| **T3. Latencia por turno p50/p95** | Pendiente como KPI completo | Existe span `conversation.turn`, pero no histograma Prometheus de ese span en el stack actual. Se visualizan por separado las latencias de llamadas LLM en SQL y fases `training_latency` en Loki, sin llamarlas latencia de turno. |
| **T4. Uso de comandos** | Implementada | `comando=Commands.*|None` en Loki, series móviles de 24 h. Incluye solicitudes bloqueadas y subacciones; no es recuento de operaciones completadas. |
| **T6. Turnos fallidos** | Parcial | Recuento de eventos de error y cortes por cuota observados, separados de A1. No se calcula porcentaje: varios logs por update y coberturas distintas impiden deduplicar el numerador. |

## Agentes y entrevista

| Métrica | Estado | Cálculo adaptado y límites |
|---|---|---|
| **A1. Errores LLM** | Implementada | `status <> 'success'` / llamadas persistidas, por agente/modelo. Desglose de estados, incluido `llm_output_limit`, no confundir con cuota de usuario. |
| **A2. Fallos RAG** | Proxy instrumentado | `training_latency phase=retrieval result=error` / todos los eventos retrieval. Catálogo vacío sin excepción cuenta como ok; no mide degradación ni todas las peticiones al trainer. Vacíos iniciales se muestran aparte como eventos. |
| **E1. Perfiles validados OK** | Proxy de formato | 1 − llamadas `llm_invalid_output` / llamadas interviewer. Se titula «llamadas sin fallo final de formato», no «perfiles válidos»: incluye turnos intermedios, reparaciones y otros fallos. |
| **E2. Interacciones por entrevista** | Implementada como mensajes | Mediana de mensajes interviewer `role=user` entre inicio/final del último intento completado, con finalización en rango. No es número de llamadas ni pares de turnos. |
| **E3. Tiempo por entrevista** | Implementada | Mediana global y por día de `completed_at-started_at`, finalización en rango. Incluye pausas del usuario; excluye fechas invertidas. |
| **E4. Entrevistas reiniciadas** | Proxy Loki | Usuarios con más de un comando INTERVIEW / usuarios que enviaron INTERVIEW en el rango retenido. No clasifica reset completo/a medias ni demuestra insatisfacción; incluye comandos bloqueados. |
| **Sentimiento** | Pendiente | No existen etiquetas/evaluación persistidas. No se infiere sentimiento desde logs. |

El dashboard Agentes incluye tokens totales, coste conocido/cobertura y p50/p95
de llamadas con `latency_ms > 0`, indicando cuántas llamadas tienen duración.
Las fases del entrenador se agrupan por acción/fase y resultado exitoso:
son anidadas y sus percentiles no se suman para obtener un turno.

## RAG y base vectorial

| Métrica | Estado | Cálculo adaptado y límites |
|---|---|---|
| **B1. Latencia de búsqueda p95** | Proxy de recuperación completa | Logs `phase=retrieval` existentes, incluyen embeddings y búsquedas por grupo. Embeddings se visualiza aparte; no representa latencia SQL vectorial aislada. |
| **B2. Similitud top-1** | Pendiente | El repositorio no persiste distancia; no se inventa score. |
| **B3. Índice/queries por día** | Pendiente | Falta datasource/estadísticas pgVector y muestras de contadores para diferencias diarias. Multiplicar peticiones ×7 no refleja los flujos actuales. |
| **B4. Ejercicios nunca recuperados** | Pendiente | `retrieved_exercise_ids` de planes confirmados no cubre todas las búsquedas ni proporciona el total del catálogo. |
| **B5. Contexto aportado vs utilizado** | Implementada con cobertura | IDs únicos del plan que pertenecen a `retrieved_exercise_ids` / IDs únicos aportados; muestra usados fuera del catálogo. Solo initial/renewal confirmados con traza, máximo 100 planes recientes. Swaps excluidos: su traza de alternativas no es contexto de todo el plan. Traza vacía produce ratio desconocido. |

## Despliegue y validación

No requiere desplegar la aplicación ni migrar PostgreSQL. Copiar los JSON al
provisioning ya montado por Grafana; el proveedor revisa los archivos cada
30 segundos. Si se despliega clonando Git, actualizar esos archivos en el
servidor de observabilidad. No cambia Nginx Proxy Manager ni puertos.

Validar JSON, variables, UIDs/datasources y consultas SQL sobre PostgreSQL
real con esquema actual; validar LogQL con Loki. Después comprobar filtros
dev/prod y disponibilidad real de Alloy/datasources en Grafana.
Un entorno sin registros debe mostrar ausencia de datos, no métricas inventadas.

Pruebas reproducibles:

```bash
uv run python -m pytest tests/unit_test/test_metric_dashboards.py tests/it/test_metric_dashboards.py --no-cov
# Solo contra un Loki de prueba aislado, con datos sintéticos:
METRICS_LOKI_URL=http://127.0.0.1:33100 uv run python -m pytest tests/it/test_metric_logql.py --no-cov
```

Las pruebas SQL requieren PostgreSQL de integración con las migraciones actuales.
Las de LogQL se omiten si no se configura un Loki aislado; no apuntarlas al
servidor real porque insertan logs sintéticos de validación.
