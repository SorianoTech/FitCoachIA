# Guía: Dashboard de Logs Mejorado - FitCoachIA

> 📅 Actualizado: 2026-09-16 — Dashboard v2 con visualizaciones de logs más completas

## Visión General

El dashboard **FitCoachIA - Conversaciones** fue rediseñado para ofrecer una visualización completa de logs con múltiples capas:

- **Capa 1**: Métricas de tokens LLM (histórico)
- **Capa 2**: Estado de logs en tiempo real (Stat counters)
- **Capa 3**: Throughput y actividad (series + barras)
- **Capa 4**: Debugging rápido (últimos 5 por categoría)
- **Capa 5**: Stream completo de logs (panel nativo Loki)

## Filtros Disponibles

Todos los paneles responden a estos filtros:

| Filtro | Tipo | Valor | Uso |
|--------|------|-------|-----|
| `$datasource` | Dropdown | PostgreSQL Dev / Prod | Aislar entorno |
| `$agent` | Multiselecta | interviewer, trainer, ... | Filtrar por agente LLM |
| `$telegram_user_id` | Multiselecta | IDs de chat | Seguimiento de usuario |
| `$log_level` | Multiselecta | ERROR, WARNING, INFO, DEBUG | Severidad de eventos |

**Tip**: Usa multiselecta para comparar simultáneamente (ej: `telegram_user_id=123 OR 456`)

## Paneles Explicados

### Fila 1: Métricas de Tokens (PostgreSQL)

**Panel 1: Tokens consumidos por agente**
- Tipo: Serie temporal
- Métrica: `sum(total_tokens)` agrupado por hora
- Uso: Detectar agentes que consumen más
- Correlación: Con latencia para identificar modelos lentos

**Panel 2: Top usuarios por tokens**
- Tipo: Tabla
- Columnas: telegram_user_id, agent, total_tokens, llamadas, latencia_ms
- Uso: Identificar "power users" del sistema
- Riesgo: Altos costos si cierto usuario hace muchas peticiones

**Panel 3: Latencia media del LLM**
- Tipo: Serie temporal
- Métrica: `avg(latency_ms)` por agente por hora
- Alerta: Si > 30s por 10 min → problema con el modelo
- Acción: Revisar estado del proveedor LLM (ej: OpenRoute)

**Panel 4: Llamadas por estado**
- Tipo: Serie temporal
- Métrica: `count()` agrupado por status
- Estado: Solo "success" se persiste hoy; futuros: "error", "timeout"
- Uso: Detectar degradación de servicio

### Fila 2: Estado de Logs en Tiempo Real (Loki)

**Panels 6, 7, 8: Contadores por Nivel (Stat)**
- 🔴 **Errores** (rojo)
- 🟠 **Warnings** (naranja)
- 🔵 **Infos** (azul)

Cada panel muestra el **recuento en el intervalo actual** (`$__interval`, típicamente 1 minuto).

**Cuándo usar**:
- Product Manager: "¿Hay errores activos?" → Mira los stat counters
- On-call: "¿Tasa de error elevada?" → Compara contra baseline histórico

**Queries**:
```logql
# Errores
sum(count_over_time({service_name="fitcoach-ia"} | json | level="ERROR" [$__interval]))

# Warnings
sum(count_over_time({service_name="fitcoach-ia"} | json | level="WARNING" [$__interval]))

# Infos
sum(count_over_time({service_name="fitcoach-ia"} | json | level="INFO" [$__interval]))
```

### Fila 3: Throughput y Actividad (Loki)

**Panel 9: Throughput (líneas/seg)**
- Tipo: Serie temporal
- Métrica: `rate({...} [1m])` por level
- Eje Y: Líneas por segundo
- Uso: Detectar picos de actividad, volumen relativo de cada nivel

```logql
rate({service_name="fitcoach-ia"} [1m])
```

**Panel 10: Actividad por Logger**
- Tipo: Gráfico de barras
- Métrica: `count()` agrupado por logger
- Eje X: Módulos (conversation_service, webhook, etc.)
- Uso: Identificar cuál módulo genera más logs (ruidoso)

```logql
sum by (logger) (count_over_time({service_name="fitcoach-ia"} [$__range]))
```

**Cuando usarlo**:
- "conversation_service genera muchos INFO" → Reducir verbosidad en ese módulo
- "webhook apenas tiene logs" → ¿Falta instrumentación?

### Fila 4: Debugging Rápido (Últimos 5)

**Panel 11: Últimos 5 errores**
**Panel 12: Últimos 5 warnings**

- Tipo: Panel Logs nativo de Grafana
- Sort: Descendente (nuevos primero)
- MaxLines: 5
- Expandible: Haz clic para ver JSON completo

```logql
{service_name="fitcoach-ia", level="error"} | telegram_user_id=~"$telegram_user_id"
{service_name="fitcoach-ia", level="warning"} | telegram_user_id=~"$telegram_user_id"
```

**Workflow de debugging**:
1. Ves "Contadores de logs" mostrar `🔴 Errores: 3`
2. Haz clic en panel "Últimos 5 errores"
3. Lees el más reciente
4. Extraes `trace_id` del JSON
5. Vas a Tempo con ese `trace_id` para ver la traza completa

### Fila 5: Stream de Logs Completo

**Panel 5: Stream de logs en vivo**
- Tipo: Panel Logs nativo
- MaxLines: 100
- Incluye logs JSON de la aplicación y access logs de Uvicorn
- Reemplaza: La tabla antigua (mejor UX + mejor performance)

```logql
{service_name="fitcoach-ia"}
```

**Características**:
- ✅ Collapsible JSON (haz clic en `{...}` para expandir)
- ✅ Highlighting automático (rojo para ERROR, amarillo para WARNING)
- ✅ Copy-to-clipboard en cada log
- ✅ Saltable a Tempo vía botón de trace_id
- ✅ Búsqueda inline con regex

**Cambio respecto a versión anterior**:
| Antes (tabla) | Ahora (Logs nativo) |
|---|---|
| Extrae JSON en columnas | Mantiene JSON collapsible |
| Lento con 10k+ logs | Rápido con streaming |
| No highlighting de nivel | Color automático por level |
| Sin botón a Tempo | Botón trace_id → Tempo |

## Flujos de Uso

### 1️⃣ Monitoreo proactivo (cada 15 min)

```
Dashboard → Contadores (Fila 2) → ¿Hay errores?
   SÍ → Últimos 5 errores → Abre trace_id en Tempo → Investiga
   NO → Revisa throughput (Fila 3) → ¿Normal? → Ok, sigue adelante
```

### 2️⃣ Incident response (error crítico)

```
Alerta de Grafana → Abre dashboard
   Usa $telegram_user_id = ID afectado
   Usa $log_level = ERROR
   Revisa "Últimos 5 errores"
   Copia trace_id → Abre en Tempo
   Revisa "Actividad por logger" → ¿Cuál módulo falló?
```

### 3️⃣ Debugging de usuario (slow response)

```
Usuario: "Mi bot me responde lento"
   Filtro: $telegram_user_id = su ID
   Voy a: Panel "Latencia media LLM" → Correlaciono con su actividad
   Voy a: Panel "Tokens consumidos" → ¿Cuántos prompts hizo?
   Voy a: Stream de logs → Busco palabra clave (regex)
   Comparo contra baseline → ¿Está dentro de rango normal?
```

### 4️⃣ Optimización (reducir costos/logs)

```
Ve que "conversation_service" domina "Actividad por logger"
   Abre ese archivo → Busca INFO/DEBUG verbosos
   Cambia log_level → redeploy → Vuelve al dashboard
   Compara antes/después en "Throughput"
   Calcula ahorros: [logs eliminados] × [costo por GB]
```

## Configuración recomendada

### Intervalo de refresco
- **Producción**: 1 minuto (por defecto)
- **Desarrollo local**: 30 segundos (más responsivo)

### Rango de tiempo
- **Alert triage**: Last 6 hours (contexto histórico)
- **Post-mortem**: Last 24 hours (timeline completa)
- **Trend analysis**: Last 7 days (patrones)

### Variables predefinidas
```
Desarrollo local:
  datasource = PostgreSQL Dev
  agent = All
  telegram_user_id = All
  log_level = All
  logger = conversation_service

Producción:
  datasource = PostgreSQL Prod
  agent = interviewer (selecciona agente activo)
  telegram_user_id = All (o specific user id)
   log_level = ERROR,WARNING (excluye info spam)
```

## Limitaciones y workarounds

### Limitación: LogQL no filtra por telegram_user_id como label

**Problema**: `telegram_user_id` va en el mensaje JSON, no como label de Loki.

**Solución**: Usamos `regexp` para extraerlo:
```logql
{service_name="fitcoach-ia"} | regexp `telegram_user_id=(?P<telegram_user_id>-?\d+)`
```

### Limitación: `$log_level` es hardcoded (no dynamic)

**Problema**: Loki no garantiza que todos los logs tengan label `level`.

**Solución**: `$log_level` es tipo `custom` con opciones fijas:
```json
["error", "warning", "info", "debug"]
```

Para agregar nuevos niveles, edita el dashboard → Variables → `log_level`.

### Limitación: Throughput agrupa por level, no por logger

**Problema**: `rate({...} [1m])` es costoso con label alta cardinalidad.

**Solución**: Usa panel "Actividad por logger" + throughput general.

Para high-cardinality (ej: `trace_id`), usa ad-hoc queries en Loki data source.

## Alertas relacionadas

Dos alertas provisionadas disparan en función de estos logs:

1. **Latencia del LLM elevada** — `avg(latency_ms)` > 30s por 10 min
2. **Tasa de fallos elevada** — > 20% de llamadas no success

Accede a ellas vía: Grafana → Alerting → Alert rules → "FitCoachIA"

## Próximos pasos

**v3 del dashboard (futuro)**:
- [ ] Panel "Estado del LLM" (últimas 10 respuestas + coste acumulado)
- [ ] Heatmap de usuarios activos por hora
- [ ] Correlación automática log↔traza (click log → Tempo)
- [ ] Botón "Export as CSV"
- [ ] Panel de alertas activas en tiempo real

**Mejoras en Alloy/Loki**:
- [ ] Agregar label `flow` (start, interview, doubts, progress) en los logs
- [ ] Normalizar `deployment.environment.name` como label (hoy está en metadata)

## Referencias

- Dashboard: `infra/observability/config/grafana/provisioning/dashboards/json/fitcoach-conversations.json`
- Alertas: `infra/observability/config/grafana/provisioning/alerting/rules.yml`
- Configuración Alloy: `infra/observability/config/alloy/config.alloy`
- Docs: [observabilidad.md](observabilidad.md)
