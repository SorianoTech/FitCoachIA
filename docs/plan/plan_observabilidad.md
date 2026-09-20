# Plan de observabilidad autogestionada

## Objetivo

Desplegar una plataforma de observabilidad autogestionada basada en Grafana,
Loki, Tempo, Prometheus y OpenTelemetry Collector mediante Docker Compose.
La plataforma debe estar separada de la lógica de negocio y no debe impedir
que la aplicación arranque o funcione si deja de estar disponible.

## 1. Estructura aislada

Mantener la infraestructura de observabilidad en un directorio independiente:

```text
infra/
  observability/
    compose.yml
    .env.example
    config/
      grafana/
        provisioning/
      loki/
        loki.yml
      tempo/
        tempo.yml
      prometheus/
        prometheus.yml
      otel-collector/
        otel-collector.yml
    data/
```

El directorio `data/` contendrá persistencia local cuando proceda y deberá
ignorarse en Git.

El Compose de observabilidad incluirá:

- Grafana para visualización, exploración y alertas.
- Loki para almacenamiento y consulta de logs.
- Tempo para almacenamiento y consulta de trazas.
- Prometheus para recolección y consulta de métricas.
- OpenTelemetry Collector como punto único de entrada de telemetría.
- Opcionalmente, Grafana Alloy para recolectar logs de contenedores sin
  modificar la aplicación.

La aplicación mantendrá su propio Compose y no dependerá de que el stack de
observabilidad esté levantado.

## 2. Red Docker compartida sin dependencia operativa

Crear una red Docker externa dedicada:

```bash
docker network create observability
```

Los servicios que deban intercambiar telemetría se conectarán a esa red:

```yaml
networks:
  observability:
    external: true
```

Las aplicaciones enviarán datos OTLP al Collector mediante
`otel-collector:4317` o `otel-collector:4318`. La exportación debe ser
asíncrona, no bloqueante y con colas acotadas: si el Collector no está
disponible, la aplicación continuará funcionando, aunque se pierda
temporalmente la telemetría.

Inicialmente no se expondrán Loki, Tempo ni Prometheus fuera de Docker. Sólo
se publicará Grafana en `localhost:3000`. Los puertos OTLP se expondrán en el
host únicamente cuando una aplicación fuera de Docker necesite enviar
telemetría.

## 3. Configuración del stack

### Grafana

Provisionar los siguientes datasources:

- Prometheus para métricas.
- Loki para logs.
- Tempo para trazas.

Configurar la correlación entre señales:

- Abrir logs de Loki desde una traza de Tempo filtrando por `trace_id`.
- Abrir la traza correspondiente desde logs.
- Navegar desde métricas o exemplars a la traza asociada.

Los dashboards y alertas deben aprovisionarse desde archivos versionados en
Git, no sólo desde la interfaz de Grafana.

### OpenTelemetry Collector

El Collector será la frontera técnica entre las aplicaciones y los backends.

**Receivers**

- OTLP gRPC en el puerto `4317`.
- OTLP HTTP en el puerto `4318`.
- Prometheus para recolectar métricas expuestas por infraestructura o
  aplicaciones en `/metrics`.

**Processors**

- `memory_limiter` para acotar el consumo de memoria.
- `batch` para agrupar exportaciones.
- `resource` para normalizar atributos de entorno, servicio y versión.
- `attributes` o `transform` para eliminar o redactar datos sensibles.
- `filter` para eliminar telemetría excesivamente ruidosa, como health checks,
  si se considera necesario.

**Exporters**

- Logs a Loki.
- Trazas a Tempo.
- Métricas a Prometheus, mediante un endpoint recolectado por Prometheus o
  escritura remota cuando esté justificada.

Los tiempos de espera, colas y límites de memoria deben ser estrictos para que
la observabilidad no afecte a la disponibilidad de la aplicación.

### Prometheus

Configurar scrape jobs para:

- OpenTelemetry Collector.
- Grafana, Loki, Tempo y Prometheus.
- Métricas de host y contenedores si se añaden `node-exporter` y `cAdvisor`.
- Endpoints `/metrics` de aplicaciones cuando corresponda.

Como punto de partida, utilizar una retención de 15 a 30 días, ajustada según
la capacidad de disco y las necesidades operativas.

### Loki

Para desarrollo e instalación inicial:

- Usar almacenamiento local persistente.
- Configurar retención de 7 a 14 días.
- Limitar ingesta y consultas.
- Etiquetar únicamente con valores de baja cardinalidad: `service_name`,
  `environment`, `level`, `container` y `compose_project`.

Los valores variables, como IDs de petición, usuarios, pedidos o errores,
deben incluirse en el cuerpo JSON del log, nunca como etiquetas.

### Tempo

Inicialmente usar almacenamiento local persistente con una retención de 3 a
7 días. Configurar su integración con métricas para relacionar picos de
latencia o errores con trazas específicas.

## 4. Instrumentación separada del negocio

Ubicar la integración técnica en un módulo independiente:

```text
src/
  domain/
  application/
  infrastructure/
  observability/
    telemetry-bootstrap.*
    logger.*
    instrumentation.*
```

Este módulo será responsable de:

- Inicializar OpenTelemetry al arrancar la aplicación.
- Instrumentar automáticamente HTTP, framework web, cliente HTTP, base de
  datos, caché y colas según el stack tecnológico.
- Configurar logs JSON hacia `stdout`.
- Añadir `trace_id`, `span_id`, `request_id`, servicio, entorno y versión a
  los logs.
- Cerrar los proveedores y exportadores durante el apagado.

La lógica de dominio y los casos de uso no importarán dependencias de Grafana,
Loki, Tempo, Prometheus ni OpenTelemetry Collector. Las métricas de negocio,
si son necesarias posteriormente, se implementarán como adaptadores opcionales
fuera del dominio.

## 5. Convenciones de telemetría

Adoptar los siguientes atributos:

| Atributo | Ejemplo |
| --- | --- |
| `service.name` | `api`, `worker`, `web` |
| `service.version` | SHA del commit o versión desplegada |
| `deployment.environment.name` | `development`, `production` |
| `trace_id` | Identificador de una petición distribuida |
| `request_id` | Identificador de una petición HTTP |
| `http.route` | Plantilla de ruta, no URL con IDs |
| `error.type` | Tipo estable de excepción o fallo |
| `db.system` / `db.operation.name` | Tecnología y operación de base de datos |

Los logs serán JSON y usarán los niveles `debug`, `info`, `warn` y `error`.
No deben contener contraseñas, tokens, cabeceras `Authorization`, cookies,
datos completos de pago ni información personal innecesaria.

## 6. Fases de implantación

1. Crear el Compose, volúmenes, red externa, configuraciones y
   aprovisionamiento de Grafana sin modificar la aplicación.
2. Monitorizar los propios componentes del stack y crear dashboards básicos de
   salud, memoria y disco.
3. Emitir logs JSON de aplicación a `stdout` y recolectarlos con Alloy o la
   configuración equivalente del runtime.
4. Integrar el SDK y exportador OTLP de OpenTelemetry en el arranque de cada
   servicio, con instrumentación automática de HTTP, bases de datos, clientes
   y mensajería.
5. Incorporar métricas RED (tasa de peticiones, errores y duración) y USE
   (utilización, saturación y errores).
6. Añadir métricas de negocio sólo tras disponer de las señales técnicas
   fundamentales.
7. Crear dashboards versionados y alertas con enlaces a logs y trazas.
8. Endurecer el despliegue productivo con autenticación, TLS o reverse proxy,
   límites de recursos, copias de seguridad, almacenamiento de objetos,
   retención y rotación de secretos.

## 7. Dashboards y alertas iniciales

Crear dashboards para:

- Salud de Grafana, Loki, Tempo, Prometheus y Collector.
- Tráfico HTTP, errores 4xx/5xx, latencia p50/p95/p99 y endpoints lentos.
- Duración y errores de SQL, Redis, APIs externas y colas.
- Trabajos procesados, fallidos, reintentos, antigüedad y profundidad de cola.
- Errores por servicio, versión y tipo de excepción, con acceso a trazas.

Configurar alertas para:

- Tasa de errores 5xx sostenida por encima del umbral definido.
- Latencia p95 o p99 que incumpla el objetivo de servicio.
- Aumento anómalo de fallos en dependencias.
- Collector sin recibir o exportar telemetría.
- Disco o memoria próximos al límite.
- Ausencia inesperada de tráfico o métricas de un servicio.

## 8. Operación local

El stack se iniciará de manera independiente:

```bash
cd infra/observability
docker compose up -d
```

La aplicación deberá iniciar, probarse y desplegarse sin este stack. La
exportación de telemetría se activará mediante variables de entorno; en CI y
pruebas unitarias podrá desactivarse por defecto.
