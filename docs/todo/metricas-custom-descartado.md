# Métricas custom: trabajo revertido el 21-09-2026

Nota para recordar por qué el código de métricas ya no está y qué quedó a medias.

## Qué se revirtió y qué no

**Se eliminó todo el código de aplicación**: el paquete `domain/metrics/` (bus de eventos, catálogo,
constantes), el módulo de handlers en `infrastructure/observability/`, las emisiones en
`conversation_service`, `interviewer_chain` y el repositorio, el `MeterProvider` de `telemetry.py` y
los cuatro ficheros de tests.

**Sigue en pie**, porque está commiteado y entrelazado con otro trabajo:

- El documento `docs/plan/plan-metricas-custom.md`.
- La infraestructura de la Fase 0: el exporter `prometheusremotewrite` y el pipeline `metrics` del
  Collector, `--enable-feature=exemplar-storage` y `storage.exemplars` en Prometheus, y el
  `exemplarTraceIdDestinations` del datasource de Grafana.

Es decir: **el pipeline de métricas está montado y no recibe nada**, porque la app ya no crea
`MeterProvider`. No estorba ni consume, pero conviene saberlo antes de extrañarse.

No se tocaron los commits de la rama. `34458e8 "fix conflicts"` mezcla la Fase 0 con el workflow de
deploy, el `Makefile` con `/etc/fitcoachia` y los renombrados de los compose; revertirlo habría
destruido trabajo sin relación.

## El motivo

Decisión de producto, no un fallo técnico: se prioriza cerrar la verificación de origen del webhook
antes que instrumentar métricas de negocio. El plan estaba en la Fase 5 de 7 y funcionaba.

## Lo que costó descubrir, por si se retoma

Cinco cosas que no están en el plan y que se aprendieron implementándolo:

1. **El plan tiene tres errores de secuencia.** Su Fase 1 importa `metric_handlers`, que no existe
   hasta la Fase 2; su Fase 2 importa `catalog`, que no existe hasta la Fase 3; y su Fase 4 usa
   `usage.cost_usd`, que **no existe**: `TokenUsage` no lleva el importe. El coste se calcula en
   `PostgresConversationRepository.record_token_usage` cruzando con `model_prices`, así que el evento
   de coste hay que emitirlo ahí.
2. **`AgentType` y `Commands` son `Enum` normales, no `StrEnum`.** `str(AgentType.INTERVIEWER)`
   devuelve `"AgentType.INTERVIEWER"`, no `"interviewer"`. Sin normalizar con `.value`, las etiquetas
   de Prometheus no cruzan con `token_usage.agent`, con el span ni con las labels de Loki.
3. **`prometheusremotewrite` no admite cola persistente.** Rechaza `sending_queue`, solo tiene
   `remote_write_queue` en memoria. Un reinicio del Collector pierde lo encolado. Impacto menor:
   las métricas OTLP son acumulativas y la siguiente exportación vuelve a declarar el total; lo único
   irrecuperable son los exemplars de esa tanda.
4. **El exporter `prometheus` en pull estaba muerto.** Exponía el puerto 8889 y `prometheus.yml` solo
   scrapeaba el 8888, que es la telemetría interna del Collector. Nadie leía las métricas de
   aplicación. De ahí el cambio a remote write.
5. **El código del plan no pasa el `mypy --strict` ni el `N801` de ruff del proyecto**: hay que tipar
   los decoradores del bus, evitar diccionarios de unión en la caché de instrumentos y usar CapWords
   en los nombres de clase.

## Pendiente si se retoma

Las comprobaciones de las fases 0 y 1 nunca se ejecutaron contra el servidor. Estaban documentadas en
`docs/todo/verificacion-plan-metricas.md`, que se eliminó con el resto; se pueden reconstruir desde
el plan.
