En este proyecto, OpenTelemetry exporta principalmente **trazas**.

**Flujo actual**

```text
FitCoachIA
  └─ crea spans automáticamente
       └─ OTLP/gRPC → otel-collector:4317
            ├─ trazas → Tempo
            ├─ logs OTLP → Loki, si alguna fuente los envía
            └─ métricas OTLP → Prometheus, si alguna fuente las envía
```

La configuración está en `telemetry.py`:

1. `configure_telemetry(app)` se ejecuta durante el arranque en `main.py`.
2. Si existe `otel_exporter_otlp_endpoint`, crea un `TracerProvider`.
3. Usa `OTLPSpanExporter`, con transporte gRPC.
4. `BatchSpanProcessor` agrupa spans y los envía de forma asíncrona.
5. Al apagar la aplicación, `shutdown_telemetry()` intenta vaciar el buffer pendiente.

El endpoint actual es:

```text
http://fitcoach-otel-collector:4317
```

Está configurado en `.env.dev`. El puerto `4317` corresponde a OTLP sobre gRPC; el `4318` sería OTLP sobre HTTP.

**Qué instrumenta automáticamente**

- Peticiones entrantes de FastAPI.
- Peticiones HTTP salientes mediante `httpx`.
- Consultas de SQLAlchemy.
- Un span propio `conversation.turn` por cada mensaje procesado, definido en `conversation_service.py`.

Ese span incluye atributos como:

- `telegram_user_id`
- `chat_id`
- `command`
- `agent`
- `llm.total_tokens`
- `llm.calls`

El Collector recibe todo en `otel-collector.yml`:

- Aplica límite de memoria.
- Añade `deployment.environment.name`.
- Elimina cabeceras `Authorization` y cookies.
- Agrupa los datos durante hasta 5 segundos.
- Envía las trazas a Tempo.

Después, Tempo genera métricas derivadas de las trazas, como:

```text
traces_spanmetrics_calls_total
traces_spanmetrics_latency_bucket
```

Estas métricas permiten consultar volumen, errores y latencias p50/p95/p99 en Prometheus.

La distinción importante es que **la aplicación todavía no crea métricas propias con `MeterProvider`, `Counter` o `Histogram`**. Las métricas actuales proceden principalmente de:

1. Métricas internas del Collector.
2. Métricas derivadas por Tempo a partir de las trazas.
3. Métricas internas de Prometheus, Grafana, Loki y Tempo.

Para verificar que se exportan trazas:

```bash
docker logs fitcoach-ia | grep -i "tracing export enabled"
docker logs fitcoach-otel-collector
```

Y para revisar las métricas derivadas:

```promql
traces_spanmetrics_calls_total
```

en el explorador de Prometheus o Grafana.