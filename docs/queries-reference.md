# Referencia: Queries LogQL y SQL del Dashboard

## 📊 Panel 1: Tokens consumidos por agente

**Tipo**: Timeseries | **DataSource**: PostgreSQL

```sql
SELECT 
  date_trunc('hour', created_at) AS time, 
  agent, 
  sum(total_tokens) AS tokens 
FROM token_usage 
WHERE $__timeFilter(created_at) 
  AND agent IN ($agent) 
  AND chat_id::text IN ($telegram_user_id) 
GROUP BY 1, agent 
ORDER BY 1
```

---

## 📊 Panel 2: Top usuarios por tokens consumidos

**Tipo**: Table | **DataSource**: PostgreSQL

```sql
SELECT 
  chat_id AS telegram_user_id, 
  agent, 
  sum(total_tokens) AS total_tokens, 
  count(*) AS llamadas, 
  round(avg(latency_ms)) AS latencia_media_ms 
FROM token_usage 
WHERE $__timeFilter(created_at) 
  AND agent IN ($agent) 
  AND chat_id::text IN ($telegram_user_id) 
GROUP BY chat_id, agent 
ORDER BY total_tokens DESC 
LIMIT 20
```

---

## 📊 Panel 3: Latencia media del LLM por agente

**Tipo**: Timeseries | **DataSource**: PostgreSQL

```sql
SELECT 
  date_trunc('hour', created_at) AS time, 
  agent, 
  avg(latency_ms) AS latencia_ms 
FROM token_usage 
WHERE $__timeFilter(created_at) 
  AND agent IN ($agent) 
  AND chat_id::text IN ($telegram_user_id) 
GROUP BY 1, agent 
ORDER BY 1
```

---

## 📊 Panel 4: Llamadas al LLM por estado

**Tipo**: Timeseries | **DataSource**: PostgreSQL

```sql
SELECT 
  date_trunc('hour', created_at) AS time, 
  status, 
  count(*) AS llamadas 
FROM token_usage 
WHERE $__timeFilter(created_at) 
  AND agent IN ($agent) 
  AND chat_id::text IN ($telegram_user_id) 
GROUP BY 1, status 
ORDER BY 1
```

---

## 📊 Panel 6: Contadores de Errores

**Tipo**: Stat (instant) | **DataSource**: Loki

```logql
sum(count_over_time({service_name="fitcoach-ia"} | json | level="ERROR" [$__interval]))
```

**Notas**:
- `$__interval` = intervalo dinámico (típicamente 1 min en dashboard)
- Retorna un único número (instant query)
- Color: rojo (thresholds configuration)

---

## 📊 Panel 7: Contadores de Warnings

**Tipo**: Stat (instant) | **DataSource**: Loki

```logql
sum(count_over_time({service_name="fitcoach-ia"} | json | level="WARNING" [$__interval]))
```

---

## 📊 Panel 8: Contadores de Infos

**Tipo**: Stat (instant) | **DataSource**: Loki

```logql
sum(count_over_time({service_name="fitcoach-ia"} | json | level="INFO" [$__interval]))
```

---

## 📊 Panel 9: Throughput (líneas/seg)

**Tipo**: Timeseries | **DataSource**: Loki

```logql
rate({service_name="fitcoach-ia"} [1m])
```

**Notas**:
- `rate(...[1m])` = tasa de cambio en líneas por segundo
- Automáticamente agrupa por `level` en la leyenda
- Eje Y = líneas/seg

**Variantes**:
```logql
# Solo errores
rate({service_name="fitcoach-ia"} | json | level="ERROR" [1m])

# Con breakdown por logger
sum by (logger) (rate({service_name="fitcoach-ia"} [1m]))
```

---

## 📊 Panel 10: Actividad por Logger

**Tipo**: Barchart | **DataSource**: Loki

```logql
sum by (logger) (count_over_time({service_name="fitcoach-ia"} [$__range]))
```

**Notas**:
- `$__range` = rango temporal completo del dashboard (ej: 24h)
- `sum by (logger)` = agrupa por módulo Python
- Eje X = módulos (conversation_service, webhook, etc.)
- Eje Y = recuento total

---

## 📊 Panel 11: Últimos 5 Errores

**Tipo**: Logs | **DataSource**: Loki

```logql
{service_name="fitcoach-ia"} | json | level="ERROR" | regexp `telegram_user_id=(?P<telegram_user_id>-?\d+)` | telegram_user_id=~"$telegram_user_id"
```

**Opciones del panel**:
- Max lines: 5
- Sort order: Descendente (nuevos primero)
- Show labels: auto
- Show time: true

**Notas**:
- `| telegram_user_id=~"$telegram_user_id"` = filtro por regexp (porque `telegram_user_id` está en el mensaje, no es label)
- Expandible: haz clic en `{...}` para ver JSON completo
- Saltable a Tempo: haz clic en `trace_id` → nueva pestaña

---

## 📊 Panel 12: Últimos 5 Warnings

**Tipo**: Logs | **DataSource**: Loki

```logql
{service_name="fitcoach-ia"} | json | level="WARNING" | regexp `telegram_user_id=(?P<telegram_user_id>-?\d+)` | telegram_user_id=~"$telegram_user_id"
```

---

## 📊 Panel 5: Stream de Logs en Vivo

**Tipo**: Logs | **DataSource**: Loki

```logql
{service_name="fitcoach-ia"}
```

**Opciones del panel**:
- Max lines: 100
- Sort order: Descendente (nuevos primero)
- Show labels: auto
- Show time: true
- Wrap log message: false

El stream no usa `| json` porque también contiene líneas de access log de
Uvicorn en texto plano. Aplicar ese parser a dichas líneas genera
`JSONParserErr`, aunque la petición haya terminado correctamente con HTTP 200.

**Variantes con filtros adicionales**:
```logql
# Solo errores de un usuario específico
{service_name="fitcoach-ia"} | json | level="ERROR" | regexp `telegram_user_id=(?P<telegram_user_id>-?\d+)` | telegram_user_id="123456789"

# Solo conversation_service
{service_name="fitcoach-ia"} | logger="conversation_service"

# Combinación: warnings de conversation_service
{service_name="fitcoach-ia"} | json | level="WARNING" | regexp `conversation_service`
```

---

## 🔍 LogQL Cheat Sheet

### Estructura básica
```logql
{label1="value1", label2="value2"}     # Selecciona logs con estos labels
| pipeline filter 1                     # Aplica filtro/transformación
| pipeline filter 2                     # Cadena de transformaciones
```

### Operadores comunes
```logql
# Labels
{job="fitcoach-ia"}                     # Igualdad
{level=~"error|warning"}                # Regex
{service_name!="other"}                 # No igual

# Pipeline stages
| json                                  # Extrae JSON
| regexp `pattern`                      # Busca patrón
| logfmt                                # Parsea logfmt
| drop __line__                         # Descarta línea original
```

### Ejemplos avanzados
```logql
# Contar líneas por nivel en rango horario
sum by (level) (count_over_time({service_name="fitcoach-ia"} [1h]))

# Tasa de errores por minuto
rate({service_name="fitcoach-ia"} | json | level="ERROR" [1m])

# Histograma de duración (si está en log como duration_ms)
{service_name="fitcoach-ia"} | json | duration_ms > 1000

# Logs con palabra clave específica
{service_name="fitcoach-ia"} |= "OutOfMemory"

# Grep inverso (NOT)
{service_name="fitcoach-ia"} != "DEBUG"
```

---

## 🛠️ Cómo personalizar queries

### Agregar nuevo nivel de log
Si agregas `debug` como nivel en la app:

1. **Stat counter (Panel nuevo)**:
   ```logql
  sum(count_over_time({service_name="fitcoach-ia"} | json | level="DEBUG" [$__interval]))
   ```

2. **Actualizar throughput** (se agrega automáticamente)

3. **Crear panel "Últimos 5 debugs"** (copiando Panel 11, cambiar `level="error"` → `level="debug"`)

### Agregar nuevo logger
Si agregás logging en `trainer_service.py`:

1. **Ya aparecerá automáticamente en Panel 10** (Actividad por logger)
2. **Para filtrar en stream**: Usa dropdown `$logger` → selecciona `trainer_service`

### Agregar filtro por campo JSON custom
Si quieres filtrar por `session_id` que está en el JSON:

```logql
{service_name="fitcoach-ia"} | json | session_id="abc123"
```

**Pero mejor opción**: Agregar `session_id` como label en Alloy (`config.alloy`)

```alloy
json_parser {
  parse_from = "body"
  parse_to = "parsed"
}
labels_masker {
  labels_to_keep = [session_id]
}
```

---

## 📌 Referencia rápida: $__variable

| Variable | Valor Típico | Uso |
|----------|-------------|-----|
| `$__interval` | `1m`, `5m` | Granularidad de agregación (stat counters) |
| `$__range` | `24h`, `7d` | Rango temporal completo del dashboard |
| `$__timeFilter()` | `WHERE ts BETWEEN ...` | En SQL: filtro de tiempo automático |
| `$datasource` | postgres, loki | Selecciona DataSource dinámicamente |
| `$agent` | interviewer, trainer | De template variable (multiselecta) |
| `$telegram_user_id` | 123456789, ... | De template variable (multiselecta) |
| `$log_level` | ERROR, WARNING, INFO, DEBUG | De template variable (multiselecta) |

---

## 🧪 Testing queries en Grafana

1. Abre Explore (icono brújula)
2. Selecciona datasource (Loki o PostgreSQL)
3. Escribe/pega la query
4. Presiona Shift+Enter o haz clic en "Run query"
5. Ajusta y guarda

**Tips**:
- Empieza simple, luego complejiza
- Usa `| limit 10` al testear (performance)
- Verifica que tiempos coincidan con tu rango del dashboard

---

## 📚 Referencias

- Docs Grafana: https://grafana.com/docs/grafana/latest/datasources/loki/
- Docs LogQL: https://grafana.com/docs/loki/latest/logql/
- Docs PostgreSQL datasource: https://grafana.com/docs/grafana/latest/datasources/postgres/
