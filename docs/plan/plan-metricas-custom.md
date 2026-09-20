# Plan: métricas custom vía OTLP con exemplars

Complementa a `plan/plan_observabilidad.md` y a `observabilidad.md`. Cubre la fase 6
del plan original («métricas de negocio») y adelanta parte de la 5.

## 0. Punto de partida

Lo que hay hoy, según `observabilidad.md`:

- La app exporta **solo trazas** por OTLP (`configure_telemetry` instrumenta
  FastAPI, HTTPX y SQLAlchemy, más el span propio `conversation.turn`).
- Las métricas en Prometheus vienen del `metrics_generator` de Tempo
  (`traces_spanmetrics_*`), no de la app.
- Los logs llegan a Loki vía Alloy, leyendo el socket de Docker. No pasan por
  el Collector.
- Tokens, coste y latencia del LLM se persisten en Postgres (`token_usage`) y
  los dashboards y alertas los consultan por SQL.

Lo que falta: un `MeterProvider` en la app, y un pipeline de métricas en el
Collector.

## 1. Decisiones previas

**D1 — Push OTLP, sin `/metrics` en la app.** Coherente con el punto único de
entrada que ya define el plan. La app no expone ningún puerto de métricas.

**D2 — Opción A: las automáticas mandan, el `metrics_generator` se apaga.** En
cuanto exista el `MeterProvider`, `FastAPIInstrumentor` empieza a publicar sus
métricas HTTP sin que nadie las pida: ya obtuvo su meter del proveedor global
al instrumentar. Eso solapa con `traces_spanmetrics_*`, que hoy es el origen de
las RED. Se resuelve quedándose con las automáticas — se calculan sobre el 100%
de las peticiones, no sobre las trazas muestreadas — y desactivando el
`span-metrics` de Tempo. **Implica rehacer los paneles de Grafana que hoy
consultan `traces_spanmetrics_*`**; detalle en el anexo 12.

**D2.bis — Nombres semánticos estables desde el primer despliegue.** Se define
`OTEL_SEMCONV_STABILITY_OPT_IN=http` en el entorno de la app. Sin ella la
instrumentación emite los nombres antiguos, en milisegundos, y habría que
rehacer los dashboards una segunda vez.

**D3 — `token_usage` sigue siendo la fuente contable.** Las métricas de tokens
y coste son para alertar y ver tendencias, no para facturar: un reinicio de la
app resetea los counters y el scrape muestrea. La tabla no se toca.

**D4 — Ninguna etiqueta de alta cardinalidad.** `telegram_user_id`, `chat_id`,
`thread` y `update` **nunca** son atributos de métrica. Van en el span (ya
están) y en la tabla. En métricas solo entran `agent`, `command`, `model`,
`status`, `result`.

**D5 — El dominio no importa OpenTelemetry.** Se emite un evento tipado; el
único módulo que conoce el SDK es el handler, en `infrastructure/observability`.
Es lo que el plan pide en su sección 4.

## 2. Fase 0 — Infraestructura (sin tocar la app)

### 2.1 Pipeline de métricas en el Collector

`infra/observability/config/otel-collector/otel-collector.yml`:

```yaml
exporters:
  prometheusremotewrite:
    endpoint: http://prometheus:9090/api/v1/write
    add_metric_suffixes: true
    resource_to_telemetry_conversion:
      enabled: false        # ver aviso abajo
    remote_write_queue:
      enabled: true
      queue_size: 5000
    timeout: 5s

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch, resource]
      exporters: [prometheusremotewrite]
```

Reutiliza los mismos `processors` que ya usan trazas y logs, incluido el de
redacción de cabeceras.

Sobre `resource_to_telemetry_conversion`: convierte **todos** los atributos de
recurso en etiquetas de cada serie. Con `service.version` puesto al SHA del
commit, cada despliegue crearía series nuevas. Déjalo en `false`: el atributo
sigue disponible en la métrica `target_info`, que se puede cruzar por
`job`/`instance`.

### 2.2 Prometheus

`infra/observability/compose.yml`, argumentos del servicio `prometheus`:

```yaml
command:
  - --config.file=/etc/prometheus/prometheus.yml
  - --storage.tsdb.retention.time=30d
  - --web.enable-remote-write-receiver
  - --enable-feature=exemplar-storage
```

El receptor de remote write ya debe estar activo, porque el
`metrics_generator` de Tempo escribe por ahí. Verifícalo antes de tocar nada.
El flag de exemplars es nuevo y sí hace falta: sin él Prometheus acepta el
write pero descarta los exemplars en silencio.

Opcionalmente, acotar el buffer en `prometheus.yml`:

```yaml
storage:
  exemplars:
    max_exemplars: 100000
```

### 2.3 Grafana

`config/grafana/provisioning/datasources/datasources.yml`, en el datasource de
Prometheus:

```yaml
jsonData:
  exemplarTraceIdDestinations:
    - name: trace_id
      datasourceUid: tempo      # el uid real del datasource de Tempo
      urlDisplayLabel: Ver traza
```

`trace_id` es el nombre exacto de la etiqueta que genera el exporter de remote
write al traducir un exemplar de OTLP. Si se escribe `traceID` o `traceId` el
enlace no aparece y no hay ningún error visible.

### 2.4 Verificación de la fase 0

Nada de esto depende de la app. Antes de seguir:

```bash
cd infra/observability
docker compose up -d --force-recreate prometheus otel-collector grafana
docker compose logs --tail=50 otel-collector | grep -i error
```

Y en Grafana, Explore → Prometheus → `traces_spanmetrics_calls_total` debe
seguir respondiendo igual que antes.

## 3. Fase 1 — MeterProvider en la app

Extender `fitcoach/infrastructure/observability/telemetry.py`, manteniendo el
comportamiento no-op:

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

_meter_provider: MeterProvider | None = None


def _configure_metrics(endpoint: str, resource: Resource) -> None:
    global _meter_provider
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True, timeout=5),
        export_interval_millis=15_000,
    )
    _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(_meter_provider)

    # registra los handlers del bus; sin este import las métricas no existen
    import fitcoach.infrastructure.observability.metric_handlers  # noqa: F401


def shutdown_telemetry() -> None:
    if _meter_provider is not None:
        _meter_provider.shutdown(timeout_millis=5000)
```

Puntos a respetar:

- Se llama desde `configure_telemetry` solo si `otel_exporter_otlp_endpoint`
  está definida. Sin ella, no se crea `MeterProvider` y `emit` no hace nada.
- El `resource` es el mismo que ya se construye para trazas: `service.name`,
  `service.version`, `deployment.environment.name`. No duplicar la definición.
- `shutdown_telemetry` va en el `lifespan` de FastAPI, junto al cierre del
  `TracerProvider`. Sin él se pierde el último intervalo de exportación.
- El `timeout=5` del exporter importa: si el Collector está caído, el hilo de
  exportación no debe quedarse colgado.

### Dependencias

```
opentelemetry-sdk>=1.29
opentelemetry-exporter-otlp-proto-grpc>=1.29
```

Los exemplars se implementaron en el SDK de Python en la 1.28.0, con
correcciones en la 1.28.1 (exportación de exemplars sin contexto). Pinar desde
1.29 evita ese camino. El filtro por defecto ya es `trace_based`; si hiciera
falta forzarlo: `OTEL_METRICS_EXEMPLAR_FILTER=trace_based`.

### Variables de entorno de la app

En `.env.dev` y `.env.prod`, junto a las que ya existen:

```bash
otel_exporter_otlp_endpoint=http://fitcoach-otel-collector:4317   # ya presente
OTEL_SEMCONV_STABILITY_OPT_IN=http
```

`OTEL_SEMCONV_STABILITY_OPT_IN` la lee la instrumentación al arrancar, no
`OTelSettings`, así que debe estar en el entorno del proceso. Valores posibles:
`http` (solo nombres nuevos), `http/dup` (ambos durante una migración, a costa
de duplicar series). No se añade a `OTelSettings` porque no es configuración de
la app: la consume el SDK directamente.

### Verificación: qué instrumentaciones publican métricas

`telemetry.py` instrumenta FastAPI, HTTPX y SQLAlchemy. De las tres, solo la de
FastAPI tiene camino de métricas confirmado; HTTPX y SQLAlchemy son
instrumentaciones principalmente de spans y su soporte de métricas depende de la
versión instalada. Antes de diseñar paneles sobre ellas, comprobarlo:

```python
# temporal, como segundo reader junto al OTLP
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

readers = [reader, PeriodicExportingMetricReader(
    ConsoleMetricExporter(), export_interval_millis=10_000)]
```

Lanzar tráfico un minuto, leer los nombres de instrumento que aparecen por
stdout y anotarlos. Luego quitar el reader de consola. Esa lista es la que
determina qué queda descubierto al apagar `span-metrics` (ver 12.7).

## 4. Fase 2 — Bus de eventos

### `fitcoach/application/events/base.py`

```python
from dataclasses import dataclass
from typing import ClassVar, Literal


@dataclass(frozen=True)
class MetricSpec:
    name: str
    doc: str
    labelnames: tuple[str, ...] = ()
    unit: str = "1"
    buckets: tuple[float, ...] | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class MetricEvent:
    spec: ClassVar[MetricSpec]

    def attributes(self) -> dict[str, str]:
        return {n: str(getattr(self, n)) for n in self.spec.labelnames}


@dataclass(frozen=True, kw_only=True, slots=True)
class CounterEvent(MetricEvent):
    amount: float = 1.0


@dataclass(frozen=True, kw_only=True, slots=True)
class UpDownEvent(MetricEvent):
    op: Literal["inc", "dec"] = "inc"
    value: float = 1.0


@dataclass(frozen=True, kw_only=True, slots=True)
class HistogramEvent(MetricEvent):
    value: float
```

`kw_only=True` es obligatorio: sin él, los campos con valor por defecto de la
clase base impiden que las subclases declaren campos requeridos.

### `fitcoach/application/events/bus.py`

```python
import logging
from collections import defaultdict
from typing import Callable, TypeVar

log = logging.getLogger(__name__)
E = TypeVar("E")
_handlers: dict[type, list[Callable]] = defaultdict(list)


def subscribe(tipo: type[E]):
    def deco(fn: Callable[[E], None]):
        _handlers[tipo].append(fn)
        return fn
    return deco


def emit(evento) -> None:
    for cls in type(evento).__mro__:
        for h in _handlers.get(cls, ()):
            try:
                h(evento)
            except Exception:
                log.exception("handler %s falló para %s", h, type(evento).__name__)


def clear() -> None:
    _handlers.clear()
```

El `try/except` no es decorativo: instrumentar nunca debe tumbar un turno de
conversación. El recorrido del MRO permite que un único handler por tipología
atienda a todos los eventos de esa familia.

Este módulo no importa OpenTelemetry. Vive en `application` y el dominio puede
emitir sin arrastrar infraestructura.

### `fitcoach/infrastructure/observability/metric_handlers.py`

```python
from opentelemetry import metrics
from fitcoach.application.events.base import CounterEvent, UpDownEvent, HistogramEvent
from fitcoach.application.events.bus import subscribe
from fitcoach.application.events import catalog  # noqa: F401 -> define los eventos

_meter = metrics.get_meter("fitcoach.domain")
_cache: dict[str, object] = {}


def _get(spec, factory):
    inst = _cache.get(spec.name)
    if inst is None:
        inst = _cache[spec.name] = factory(spec)
    return inst


@subscribe(CounterEvent)
def _on_counter(e: CounterEvent) -> None:
    inst = _get(e.spec, lambda s: _meter.create_counter(
        s.name, unit=s.unit, description=s.doc))
    inst.add(e.amount, e.attributes())


@subscribe(UpDownEvent)
def _on_updown(e: UpDownEvent) -> None:
    inst = _get(e.spec, lambda s: _meter.create_up_down_counter(
        s.name, unit=s.unit, description=s.doc))
    inst.add(e.value if e.op == "inc" else -e.value, e.attributes())


@subscribe(HistogramEvent)
def _on_histogram(e: HistogramEvent) -> None:
    inst = _get(e.spec, lambda s: _meter.create_histogram(
        s.name, unit=s.unit, description=s.doc,
        explicit_bucket_boundaries_advisory=list(s.buckets) if s.buckets else None))
    inst.record(e.value, e.attributes())
```

Tres handlers en total. Añadir una métrica nueva será añadir una dataclass, sin
tocar este fichero.

## 5. Fase 3 — Catálogo inicial

`fitcoach/application/events/catalog.py`. Nombres sin sufijo `_total` ni
`_seconds`: los añade la traducción a Prometheus a partir del tipo y la unidad.

| Evento | Tipo | Métrica | Unidad | Atributos |
|---|---|---|---|---|
| `TurnoProcesado` | Counter | `conversation_turns` | `1` | `command`, `agent`, `result` |
| `DuracionTurno` | Histogram | `conversation_turn_duration` | `s` | `command`, `agent` |
| `LlamadaLLM` | Histogram | `llm_call_duration` | `s` | `model`, `agent`, `status` |
| `TokensLLM` | Counter | `llm_tokens` | `1` | `model`, `agent`, `kind` (`prompt`/`completion`) |
| `CosteLLM` | Counter | `llm_cost_usd` | `1` | `model`, `agent` |
| `ReparacionJSON` | Counter | `llm_json_repairs` | `1` | `model`, `agent` |
| `EntrevistaCompletada` | Counter | `interviews_completed` | `1` | `agent` |

Ejemplo de definición:

```python
@dataclass(frozen=True, kw_only=True, slots=True)
class LlamadaLLM(HistogramEvent):
    spec = MetricSpec(
        name="llm_call_duration",
        doc="Duración de una llamada al LLM",
        labelnames=("model", "agent", "status"),
        unit="s",
        buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
    )
    model: str
    agent: str
    status: str
```

Los buckets se eligen contra el umbral que ya usas en alertas (30 s de latencia
del LLM): debe existir un corte exacto en ese valor para que el percentil sea
fiable cerca del umbral.

Cardinalidad estimada: 7 métricas, `agent` con 4 valores, `model` con 2-3,
`command` con 5, `status`/`result` con 2-3. El histograma es el caro: 8 buckets
× 3 modelos × 4 agentes × 3 estados ≈ 288 series, más `_sum` y `_count`.
Asumible. Añadir un atributo más de 10 valores lo multiplica por 10.

## 6. Fase 4 — Emisión

**`conversation_service.py`**, dentro del span `conversation.turn` que ya
existe:

```python
from fitcoach.application.events.bus import emit
from fitcoach.application.events.catalog import TurnoProcesado, DuracionTurno

t0 = time.perf_counter()
try:
    respuesta = await self._procesar(update)
except Exception:
    emit(TurnoProcesado(command=command, agent=agent, result="error"))
    raise
else:
    emit(TurnoProcesado(command=command, agent=agent, result="ok"))
finally:
    emit(DuracionTurno(command=command, agent=agent,
                       value=time.perf_counter() - t0))
```

**`InterviewerChain._invoke`**, en el mismo punto donde ya se construye el
`TokenUsage`, para no recorrer la respuesta dos veces:

```python
emit(LlamadaLLM(model=usage.model, agent=agent, status="success",
                value=latency_ms / 1000))
emit(TokensLLM(model=usage.model, agent=agent, kind="prompt",
               amount=usage.prompt_tokens))
emit(TokensLLM(model=usage.model, agent=agent, kind="completion",
               amount=usage.completion_tokens))
if usage.cost_usd is not None:
    emit(CosteLLM(model=usage.model, agent=agent, amount=usage.cost_usd))
```

La llamada de reparación de JSON emite `ReparacionJSON` y su propia
`LlamadaLLM`. Hoy `token_usage.status` solo registra el camino feliz; las
métricas sí deben cubrir el fallo, con `status="error"`, porque es justo lo que
alimenta la alerta de tasa de fallos.

**Requisito para los exemplars**: todo `emit` debe ocurrir dentro de un span
activo. En `conversation_service.py` se cumple, porque el span
`conversation.turn` envuelve el turno. En cualquier punto nuevo, comprobarlo
antes de dar por hecho el enlace a la traza.

## 7. Fase 5 — Verificación de los exemplars

Cadena completa, y cada eslabón falla en silencio:

1. SDK ≥ 1.29 y filtro `trace_based` → el exemplar se adjunta.
2. El `emit` ocurre dentro de un span muestreado.
3. El exporter OTLP los serializa (automático).
4. El Collector los reenvía por remote write (automático).
5. Prometheus arrancado con `--enable-feature=exemplar-storage`.
6. El datasource declara `exemplarTraceIdDestinations` con `trace_id`.

Comprobación directa, desde dentro de la red (Prometheus no está publicado):

```bash
docker compose exec prometheus wget -qO- \
  'http://localhost:9090/api/v1/query_exemplars?query=llm_call_duration_seconds_bucket&start=<unix>&end=<unix>'
```

Debe devolver objetos con `labels.trace_id`. Si devuelve lista vacía pero la
métrica sí existe en `/api/v1/query`, el problema está entre los pasos 1 y 5;
si devuelve exemplars pero Grafana no muestra el enlace, está en el 6.

En el panel, además, hay que activar la casilla de exemplars en las opciones de
la query; no se muestran por defecto aunque existan.

## 8. Fase 6 — Dashboards y alertas

Consultas base para el dashboard nuevo, «FitCoachIA - Negocio»:

```promql
# Turnos por minuto, por comando
sum by (command) (rate(conversation_turns_total[5m])) * 60

# Tasa de error de turnos
sum(rate(conversation_turns_total{result="error"}[5m]))
  / sum(rate(conversation_turns_total[5m]))

# p95 de latencia del LLM por modelo  (panel con exemplars)
histogram_quantile(0.95,
  sum by (le, model) (rate(llm_call_duration_seconds_bucket[5m])))

# Coste por hora
sum(rate(llm_cost_usd_total[1h])) * 3600

# Tokens por agente
sum by (agent, kind) (rate(llm_tokens_total[5m]))
```

Las dos alertas actuales se pueden migrar de SQL a PromQL. Merece la pena por
dos razones: dejan de depender de que Postgres esté sano, y con
`deployment_environment_name` como selector desaparece la duplicación
`[dev]`/`[prod]` en el fichero de reglas.

```promql
# Latencia del LLM por encima del umbral
histogram_quantile(0.95,
  sum by (le) (rate(llm_call_duration_seconds_bucket{
    deployment_environment_name="prod"}[15m]))) > 30

# Tasa de fallos del LLM
sum(rate(llm_call_duration_seconds_count{status!="success"}[15m]))
  / sum(rate(llm_call_duration_seconds_count[15m])) > 0.2
```

El nombre exacto del atributo de entorno en Prometheus hay que confirmarlo
contra una serie real: la normalización de puntos a guiones bajos depende de la
versión del exporter.

Mantener el dashboard de tokens sobre Postgres. Son vistas distintas: el SQL da
el detalle por usuario y el histórico exacto; Prometheus da la tendencia y
dispara alertas.

## 9. Fase 7 — Tests

El bus se prueba sin OpenTelemetry:

```python
@pytest.fixture
def eventos():
    from fitcoach.application.events import bus
    capturados = []
    bus.clear()
    bus.subscribe(MetricEvent)(capturados.append)
    yield capturados
    bus.clear()
```

Y se asserta sobre la lista. En CI no se define `otel_exporter_otlp_endpoint`,
así que no hay `MeterProvider`, no hay exportación y no hay red. El
comportamiento ya validado de la telemetría no-op se mantiene.

Un test de regresión que conviene: que `metric_handlers` se importe al arrancar
con endpoint configurado. El fallo de «métricas siempre a cero» por un import
que nadie ejecuta es el más común de este diseño y no da ningún error.

## 10. Checklist de despliegue

- [ ] Prometheus con `--enable-feature=exemplar-storage` y remote write activo
- [ ] Pipeline `metrics` en el Collector, con `resource_to_telemetry_conversion: false`
- [ ] Datasource de Prometheus con `exemplarTraceIdDestinations: trace_id`
- [ ] `opentelemetry-sdk>=1.29` en las dependencias
- [ ] `MeterProvider` creado solo si hay endpoint; `shutdown` en el `lifespan`
- [ ] `metric_handlers` importado en el arranque
- [ ] Ningún atributo de métrica con id de usuario, chat o petición
- [ ] Buckets alineados con los umbrales de alerta
- [ ] Verificado `query_exemplars` con resultados no vacíos
- [ ] Dashboard nuevo versionado en `provisioning/dashboards/json/`

## 11. Riesgos

**Cardinalidad.** Es el único fallo de este plan que puede tumbar Prometheus.
Revisar cada atributo nuevo antes de mezclarlo.

**Temporalidad.** El exporter OTLP de Python es acumulativo por defecto, que es
lo que Prometheus espera. No poner
`OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta`: los counters
aparecerían reiniciándose constantemente.

**Reinicios.** Un despliegue resetea los counters. `rate()` lo gestiona, pero
cualquier panel que use `increase()` sobre ventanas largas mostrará saltos.
Para totales exactos, `token_usage`.

**Duplicidad con spanmetrics.** Ocurre desde el primer despliegue, no «más
adelante»: las métricas HTTP del instrumentor aparecen junto con las custom.
Tener las dos fuentes es pagar dos veces por lo mismo y ver números ligeramente
distintos en paneles vecinos, porque se calculan sobre poblaciones distintas
(spanmetrics depende del muestreo de trazas). Resolver en la fase 0 con una de
las opciones del anexo.

**Alloy y el socket de Docker.** No cambia con esto, pero sigue siendo el
privilegio más amplio del stack. Anotado ya como limitación conocida.

## 12. Anexo — métricas automáticas de la app

Las métricas del catálogo (sección 5) no son las únicas que la app publicará.
El `MeterProvider` de la fase 1 activa también las de la instrumentación que ya
está en `telemetry.py`. Este anexo deja constancia de cuáles son, por qué
aparecen sin pedirlas y qué hacer con el solapamiento.

### 12.1 Qué aparece

| Métrica OTel | En Prometheus | Origen |
|---|---|---|
| `http.server.request.duration` | `http_server_request_duration_seconds_*` | FastAPI |
| `http.server.active_requests` | `http_server_active_requests` | FastAPI |
| `http.server.request.body.size` | `http_server_request_body_size_bytes_*` | FastAPI |
| `http.server.response.body.size` | `http_server_response_body_size_bytes_*` | FastAPI |

Atributos: `http.request.method`, `http.route`, `http.response.status_code`,
`server.address`. `http.route` usa la plantilla de ruta, no la URL con ids.

De HTTPX y SQLAlchemy no se da por hecho nada: son instrumentaciones de spans y
lo que publiquen como métricas depende de la versión del paquete. La lista real
sale del paso de verificación de la fase 1.

### 12.2 Por qué no se pueden «no activar»

`FastAPIInstrumentor.instrument_app(app)` pide un meter al proveedor global en
el momento de instrumentar. Si todavía no hay `MeterProvider` real, recibe un
proxy que delega en cuanto se registra uno. Resultado: el día que se cree el
`MeterProvider` para las métricas custom, las HTTP empiezan a fluir por el
mismo exportador sin tocar una línea.

### 12.3 Decisión: opción A

**A — Quedarse con las automáticas y apagar `span-metrics` de Tempo.**
**Elegida.** Las métricas del instrumentor se calculan sobre el 100% de las
peticiones; las spanmetrics, sobre las trazas que sobrevivan al muestreo.
Además usan las mismas convenciones semánticas que los spans, así que los
atributos casan entre paneles.

> **Aviso: hay que rehacer los paneles de Grafana.** Todo panel que hoy
> consulte `traces_spanmetrics_calls_total` o `traces_spanmetrics_latency_*`
> dejará de devolver datos nuevos. La migración debe hacerse **antes** de
> apagar el generador, no después, para poder comparar ambas series en paralelo
> durante unos días y comprobar que los números cuadran. Los dashboards están
> versionados en `provisioning/dashboards/json/`, así que el cambio es un PR,
> no clics en la interfaz. Las series antiguas siguen consultables durante los
> 30 días de retención.

Equivalencias para la migración:

| Antes | Después |
|---|---|
| `rate(traces_spanmetrics_calls_total[5m])` | `rate(http_server_request_duration_seconds_count[5m])` |
| `histogram_quantile(0.95, ...traces_spanmetrics_latency_bucket...)` | `histogram_quantile(0.95, ...http_server_request_duration_seconds_bucket...)` |
| Filtro por `span_name` | Filtro por `http_route` |
| Filtro por `status_code` (span) | Filtro por `http_response_status_code` |
| Latencia del span `conversation.turn` | `conversation_turn_duration_seconds_*` (custom) |

Las dos opciones descartadas quedan documentadas por si hay que revertir:

**B — Quedarse con spanmetrics y descartar las automáticas.** Mantiene los
dashboards intactos. Requiere una vista que las tire al suelo:

```python
from opentelemetry.sdk.metrics.view import View, DropAggregation

views = [
    View(instrument_name="http.server.*", aggregation=DropAggregation()),
    View(instrument_name="http.client.*", aggregation=DropAggregation()),
]
MeterProvider(resource=resource, metric_readers=[reader], views=views)
```

Alternativa equivalente: pasar `meter_provider=NoOpMeterProvider()` a
`instrument_app`, lo que deja las trazas intactas y solo silencia las métricas
de esa instrumentación.

**C — Mantener ambas.** Solo si se acepta pagar dos veces el almacenamiento y
explicar en cada panel de qué fuente sale el número. Útil únicamente como
estado transitorio durante la migración descrita arriba.

### 12.4 Nombres estables

Sin `OTEL_SEMCONV_STABILITY_OPT_IN=http`, la instrumentación emite los nombres
antiguos (`http.server.duration`, en milisegundos) en lugar de los de la tabla.
Conviene fijar la variable en el entorno de la app desde el primer despliegue
para no rehacer dashboards después. `http/dup` emite ambos durante una
transición, a costa de duplicar series mientras dure.

### 12.5 Runtime del proceso

`opentelemetry-instrumentation-system-metrics` añade CPU, memoria, hilos y GC
del proceso Python (`process.runtime.cpython.*`). No está instalado y sí hay
que activarlo explícitamente. Es la parte USE que pide la fase 5 del plan
original, junto con cAdvisor y node-exporter, y puede esperar a que las métricas
de negocio estén en marcha.

### 12.6 Impacto en el checklist

Añadir a la sección 10:

- [ ] `OTEL_SEMCONV_STABILITY_OPT_IN=http` en `.env.dev` y `.env.prod`
- [ ] Verificado con `ConsoleMetricExporter` qué instrumentaciones publican métricas
- [ ] Paneles migrados de `traces_spanmetrics_*` a `http_server_request_duration_seconds_*`
- [ ] Periodo de solape verificado (ambas fuentes dando números equivalentes)
- [ ] `span-metrics` desactivado en `tempo.yml`, `service-graphs` conservado

### 12.7 Qué implica apagar el `metrics_generator`

**Tempo no se ve afectado como almacén de trazas.** El generador solo *deriva*
métricas de las trazas que ya recibe. Apagarlo no toca la ingesta, ni la
retención de 7 días, ni las consultas. Tempo sigue siendo imprescindible, y más
que antes: es el único sitio donde vive la traza, y un exemplar que apunte a un
`trace_id` inexistente no sirve de nada.

**Qué desaparece:**

- `traces_spanmetrics_calls_total` y `traces_spanmetrics_latency_*`.
- El grafo de servicios (`traces_service_graph_*`), si se apaga el generador
  entero en vez de solo el procesador `span-metrics`.
- El remote write de Tempo a Prometheus. El receptor debe seguir activo, porque
  ahora lo usa el Collector.

**Qué queda descubierto.** Spanmetrics daba RED de *cualquier* span, no solo de
los HTTP. Al apagarlo:

| Span | Cobertura tras el cambio |
|---|---|
| Peticiones HTTP (webhook) | `http_server_request_duration_seconds_*` |
| `conversation.turn` | `conversation_turn_duration_seconds_*` (custom) |
| Llamadas al LLM vía HTTPX | `llm_call_duration_seconds_*` (custom) |
| Queries de SQLAlchemy | **Sin cobertura**, salvo que la verificación de la fase 1 revele métricas de SQLAlchemy — ver 12.8 |

Las cuatro vías para cubrir la base de datos, con su recomendación, están en
12.8. La decisión se pospone hasta tener el resultado de la verificación.

Un matiz sobre el webhook: `http_server_request_duration_seconds` mide lo que
tarda el endpoint en responder. Solo equivale a la duración del turno si el
procesamiento ocurre de forma síncrona dentro de la petición; si se mueve a una
tarea en segundo plano, las dos métricas divergen y la buena es la custom.

**Punto intermedio.** En `tempo.yml` se puede dejar el generador activo solo con
el procesador `service-graphs` y quitar `span-metrics`. Conserva el grafo de
servicios, que no tiene equivalente en las métricas del instrumentor, y elimina
la duplicidad. Es la configuración recomendada.

### 12.8 Vías para métricas de base de datos

Las métricas de SQL que hoy existen no las produce `SQLAlchemyInstrumentor`:
las produce Tempo derivándolas de los spans de query. Al apagar `span-metrics`
desaparecen, y hay cuatro salidas. La decisión se toma **después** de la
verificación de la fase 1, no antes.

**V0 — No hacer nada.** La opción por defecto. Los datos no se pierden: siguen
en las trazas, con el detalle completo de qué query, cuánto tardó y dentro de
qué turno, y TraceQL permite agregarlos. Lo que se pierde es la serie temporal
barata con 30 días de retención, que solo sirve para dos cosas: dibujar
tendencias largas y disparar alertas. Hoy no hay ninguna alerta sobre latencia
de base de datos — las dos provisionadas son del LLM — así que no se está
perdiendo nada en uso. Una métrica que nadie consulta es cardinalidad pagada a
cambio de nada.

**V1 — Las del propio `SQLAlchemyInstrumentor`.** Si la verificación de la fase
1 revela que la versión instalada publica métricas (típicamente de pool de
conexiones), no hay nada que hacer: llegan solas con el `MeterProvider`.
Cubrirían saturación del pool, no latencia por query.

**V2 — Filtrar `span-metrics` en Tempo en vez de apagarlo.** El procesador
admite políticas de filtrado por span. En lugar de desactivarlo entero, se deja
generando métricas **solo para los spans de base de datos**, excluyendo los
HTTP. Se conserva la métrica de SQL sin duplicar nada y sin escribir una línea
de código. Es la más barata de las tres activas. Hay que confirmar la sintaxis
exacta contra Tempo 2.6.1 antes de comprometerse.

**V3 — Histograma custom vía eventos de SQLAlchemy.** Si se quiere latencia por
operación y V2 no encaja, la instrumentación va en `infrastructure`, nunca en
los repositorios uno a uno:

```python
# fitcoach/infrastructure/observability/db_metrics.py
import time
from sqlalchemy import event
from fitcoach.application.events.bus import emit
from fitcoach.application.events.catalog import DuracionQuery


def register(engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, params, context, executemany):
        context._otel_t0 = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, params, context, executemany):
        emit(DuracionQuery(
            operation=statement.split(None, 1)[0].lower(),   # select, insert...
            value=time.perf_counter() - getattr(context, "_otel_t0", time.perf_counter()),
        ))
```

Con su entrada en el catálogo:

```python
@dataclass(frozen=True, kw_only=True, slots=True)
class DuracionQuery(HistogramEvent):
    spec = MetricSpec(
        name="db_query_duration",
        doc="Duración de una query",
        labelnames=("operation",),
        unit="s",
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2),
    )
    operation: str
```

El atributo es la **operación**, nunca el SQL completo ni la tabla si esta sale
de una interpolación: cada sentencia distinta sería una serie nueva. Con
`select`, `insert`, `update` y `delete` la cardinalidad queda en 4 × 9 buckets.
Los buckets son mucho más bajos que los del LLM porque una query lenta lo es a
partir de decenas de milisegundos, no de segundos.

Un detalle: estos eventos ocurren dentro del span de la query, así que los
exemplars funcionan y un pico en el histograma lleva a la traza de esa query
concreta.

**Recomendación.** V0 hasta que aparezca una necesidad real. Si la verificación
de la fase 1 da V1, se aprovecha. Si más adelante hace falta alertar sobre
latencia de base de datos, probar V2 antes que V3: no añade código ni superficie
de mantenimiento.

Añadir al checklist de la sección 10:

- [ ] Decidida la vía para métricas de base de datos (V0/V1/V2/V3) tras la
      verificación de la fase 1

## 13. Nota fuera de alcance — pendiente de seguridad en el webhook

No relacionado con métricas; se anota aquí para no perderlo.

**`/webhook/response` no verifica que el emisor sea Telegram**
([webhook.py:53-61](../../src/fitcoach/api/webhook.py#L53-L61)). No hay comprobación del header
`X-Telegram-Bot-Api-Secret-Token` (soportado por `setWebhook(secret_token=...)`) ni de origen.
Cualquiera que conozca la URL puede enviar un `Update` con un `chat_id` arbitrario y disparar
`ConversationService.handle_update`: gasto de tokens/coste del LLM, escritura en Postgres y envío
de mensajes del bot a ese `chat_id`, todo atribuido a una conversación que nunca ocurrió.

Pendiente: añadir el chequeo del secret token en `telegram_webhook` (o como dependencia previa),
comparándolo contra un valor configurado (`bot_telegram_secret_token` o similar) antes de llamar a
`parse_update`.
