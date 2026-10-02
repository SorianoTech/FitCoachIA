# Cuota de consumo por chat (rate limiter)

Cada chat dispone de un presupuesto de tokens dentro de una ventana móvil. Cuando lo agota, la app
responde con un mensaje genérico y registra un `WARNING`, **sin llamar al modelo**. El objetivo es
acotar el gasto, no moderar el uso: no hay listas de usuarios ni bloqueos permanentes.

---

## 1. Calcular los valores

Tres variables de entorno, **todas opcionales**:

| Variable | Por defecto | Qué es |
|---|---|---|
| `rate_limit_token_limit` | `150000` | Punto de corte en tokens. **No es el techo.** |
| `rate_limit_soft_ratio` | `0.66` | Fracción del anterior a la que se corta lo caro. Rango `(0, 1]`. |
| `rate_limit_window_minutes` | `1440` | Ventana móvil sobre la que se suma el consumo (1440 = 24 h). |

La ventana va **en minutos, no en horas**, para que desarrollo pueda usar ventanas de pocos minutos
y verificar el corte sin esperar a mañana.

Los valores por defecto están calibrados para `gpt-5-nano`; el porqué de cada uno está en la
[sección 2](#2-decisiones-tomadas-y-por-qué).

### Fórmulas

```
soft   = rate_limit_token_limit × rate_limit_soft_ratio
margen = 2 × peor_llamada
rate_limit_token_limit = techo_real − margen
```

Y las dos condiciones que deben cumplirse **a la vez**:

```
soft  <  rate_limit_token_limit  ≤  techo_real − margen
(rate_limit_token_limit − soft)  ≥  coste de terminar una entrevista
```

### Por qué cada término

**`rate_limit_token_limit` es el punto de corte, no el techo.** El consumo se comprueba *antes* de
gastar, así que un turno que pasa el filtro lo rebasa al terminar. Un chat con 149.900 tokens supera
la comprobación y acaba en 155.000. Por eso se elige por debajo del techo real que no quieres cruzar.

**El margen es un número absoluto, no un porcentaje.** Depende del coste de un turno, no del tamaño
del presupuesto, y son magnitudes sin relación:

| `rate_limit_token_limit` | 5 % | ¿cubre un turno de ~6.000? |
|---|---|---|
| 150.000 | 7.500 | sí, justo |
| 500.000 | 25.000 | sí, de sobra |
| 20.000 | 1.000 | **no** — se rebasa igual |

**Un turno pueden ser dos llamadas.** El reintento de reparación de JSON consume tokens y no genera
turno propio —es el motivo de que `conversation_message_id` sea nullable en
[models.py](../src/fitcoach/infrastructure/database/models.py)—, de ahí el `× 2` del margen.

### Medir antes de fijar nada

```sql
-- 1. Consumo diario por chat: ¿dónde está el uso legítimo?
SELECT chat_id, SUM(total_tokens) AS tokens
FROM token_usage
WHERE created_at >= now() - interval '1 day'
GROUP BY chat_id ORDER BY tokens DESC;

-- 2. Peor llamada: la mitad del margen.
SELECT max(total_tokens) AS peor_llamada,
       percentile_disc(0.99) WITHIN GROUP (ORDER BY total_tokens) AS p99
FROM token_usage;
```

Regla práctica: **el ratio dimensiona el hueco, no el presupuesto.** Si las entrevistas se cortan a
medias, baja el ratio antes de subir el límite. El límite decide cuántas entrevistas caben al día;
el ratio decide si la que está en curso puede terminar.

---

## 2. Decisiones tomadas y por qué

Los valores por defecto salen de medir el coste real de una entrevista con `gpt-5-nano`
(`gpt-5-nano-2025-08-07`: entrada $0.05/M, salida $0.40/M).

### 2.1 Cuánto cuesta una entrevista

El historial deja de crecer en el turno 10 por `ia_history_window_messages=20`, así que el término
cuadrático del reenvío de historial se corta ahí:

```
turnos 1-10:  10 × 1.500 + 200 × 55   = 26.000   (system prompt + historial creciente)
turnos 11-15:  5 × 3.500              = 17.500   (historial ya topado)
salida:       15 × (150 + 300)        =  6.750   (respuesta + razonamiento)
                                        ───────
entrevista completa ≈ 50.000 tokens ≈ $0.005
```

Dos tercios de la salida son **tokens de razonamiento**. Con `reasoning_effort: "minimal"` la
entrevista bajaría a ~35.000 tokens, y estos umbrales podrían estrecharse en consecuencia.

### 2.2 Los tres valores

| Valor | Elegido | Cálculo |
|---|---|---|
| Peor llamada | 4.000 | Turno con el historial lleno: 3.500 de entrada + 450 de salida |
| Margen | 8.000 | `2 × 4.000` — un turno pueden ser dos llamadas |
| `rate_limit_token_limit` | **150.000** | Techo real 158.000 − 8.000 de margen. Da para **3 entrevistas al día** |
| `rate_limit_soft_ratio` | **0.66** | Hueco requerido = una entrevista completa (50.000) |
| `rate_limit_window_minutes` | **1440** | 24 h: presupuesto diario, fácil de razonar y de explicar |

El ratio sale de despejar el hueco, no al revés:

```
soft_ratio = 1 − 50.000 / 150.000 = 0,6667
```

Se redondea a **0.66**, no a 0.67, porque `int(150.000 × 0.67) = 100.500` deja el hueco en 49.500 y
se queda 500 tokens corto. Con `0.66` el umbral blando cae en **99.000** y el hueco es **51.000**.
El test `test_the_default_gap_fits_a_whole_interview` fija ese invariante.

### 2.3 Qué implica en coste

| Concepto | Valor |
|---|---|
| Un chat que agota su cuota | $0.015/día — **$0.45/mes** |
| Umbral blando (99.000) | ~2 entrevistas antes de no poder arrancar otra |
| Límite (150.000) | 3 entrevistas completas |
| Techo real alcanzable | 158.000 (~$0.016) |

El riesgo que acota no es el usuario normal —que hará una entrevista y poco más— sino el bucle o el
abuso: sin cuota, Telegram permite un mensaje por segundo y chat, lo que a ~4.000 tokens por turno
son cientos de millones de tokens al día.

### 2.4 Valores por entorno

Los defaults son los de producción. Desarrollo busca lo contrario: que el corte salte enseguida para
poder verificarlo a mano.

| | Desarrollo | Producción |
|---|---|---|
| Skill | `interviewer-dev` (3 preguntas) | `interviewer` (15 preguntas) |
| Coste de una entrevista | ~10.000 tokens | ~50.000 tokens |
| `rate_limit_token_limit` | `12000` | `150000` |
| `rate_limit_soft_ratio` | `0.1` | `0.66` |
| `rate_limit_window_minutes` | `5` | `1440` |
| Efecto | Cabe una entrevista; la siguiente `/interview` se rechaza | 3 entrevistas al día |

En desarrollo el ratio es `0.1` a propósito: con el umbral blando en 1.200 tokens, basta terminar una
entrevista para que la siguiente `/interview` se rechace, y el hueco de 10.800 sigue permitiendo
cerrar la que esté en curso. Con la ventana de 5 minutos, la cuota se recupera sola mientras pruebas.

Producción declara las tres variables **aunque coincidan con los defaults del código**: lo que rige
en el servidor queda escrito en el servidor, y ajustarlas más adelante no exige recordar que
existían. A cambio, hay dos sitios que pueden divergir si cambian los defaults.

Ambos juegos están listos para copiar en `.env.example`.

### 2.5 Lo que estos valores NO cubren

El límite es **por chat**. El TPM de la cuenta es un límite distinto y transversal: en Tier 1 son
200.000 tokens por minuto para todos los chats a la vez, es decir unos 40 turnos por minuto en total.
Esta cuota no protege de eso; si se convierte en un problema, la palanca es `max_output_tokens` y el
tier de la cuenta, no `rate_limit_token_limit`.

---

## 3. Cómo corta

Un único contador —tokens del chat en la ventana— con **dos umbrales**, de modo que lo caro caiga
primero y se pueda terminar lo empezado:

```
 consumo del chat en la ventana
   0 ─────────────── soft ─────────────── límite ─────────►
       todo OK        /interview           todo el LLM
                      cortado              cortado
```

| Entrada | Nivel | Se corta en | Respuesta |
|---|---|---|---|
| `/interview` | `SOFT` | `soft` | «No puedes iniciar una entrevista nueva por hoy, pero puedes seguir con la conversación actual.» |
| Texto libre | `HARD` | `límite` | «Has alcanzado el límite de uso por hoy. Vuelve a intentarlo más tarde.» |
| `/start`, `/doubts`, `/progress` | `UNLIMITED` | nunca | — |

Los comandos `UNLIMITED` **ni siquiera consultan el consumo**: hoy no invocan al modelo, así que la
cuota no les cuesta una query. El día que alguno llame al LLM hay que moverlo de nivel.

Ningún mensaje menciona tokens, cifras ni cuánto queda. Lo que sí dice el mensaje del nivel `SOFT`
es qué **puede** seguir haciendo el usuario, que es lo que da sentido al escalonado.

`rate_limit_soft_ratio=1.0` iguala ambos umbrales y desactiva el escalonado sin tocar código.

---

## 4. Dónde vive cada pieza

| Archivo | Responsabilidad |
|---|---|
| [domain/rate_limiter.py](../src/fitcoach/domain/rate_limiter.py) | `UsageTier`, `COMMAND_TIERS` y `UsageLimits`. **La política**: qué comando cae en qué nivel. |
| [infrastructure/config/settings.py](../src/fitcoach/infrastructure/config/settings.py) | `UsageSettings` + `to_limits()`. **La calibración**: los números. |
| [domain/constants.py](../src/fitcoach/domain/constants.py) | `QUOTA_SOFT_MESSAGE` y `QUOTA_EXCEEDED_MESSAGE`. |
| [repository/conversation_repository.py](../src/fitcoach/repository/conversation_repository.py) | Puerto `tokens_used_since(chat_id, since)`. |
| […/postgres_conversation_repository.py](../src/fitcoach/infrastructure/database/postgres_conversation_repository.py) | La query sobre `token_usage`. |
| [service/conversation_service.py](../src/fitcoach/service/conversation_service.py) | `_quota_message()` y el corte en `_process`. |

El reparto es deliberado: **la política se revisa en un PR, la calibración se ajusta sin desplegar**.
Cambiar de 142.000 a 200.000 es operación; cambiar que `/interview` caiga antes que el texto libre es
una decisión de producto.

### La query

```python
select(func.coalesce(func.sum(TokenUsageRecord.total_tokens), 0)).where(
    TokenUsageRecord.chat_id == chat_id,
    TokenUsageRecord.created_at >= since,
)
```

- **`coalesce(..., 0)`**: `SUM` sobre cero filas devuelve `NULL`, no `0`. Sin esto, el primer mensaje
  de un chat nuevo rompería la comparación con el umbral.
- **No filtra por `status`**: una llamada fallida ha consumido tokens y se ha pagado igual. Excluir
  los fallos sería el camino barato para saltarse la cuota.
- **Sin migración**: el `WHERE` coincide con el índice `ix_token_usage_chat_id_created_at` ya
  existente.
- **`since` debe ser tz-aware**. `created_at` es `TIMESTAMPTZ`; con un `datetime.now()` naive,
  asyncpg falla al comparar. Se calcula como `datetime.now(UTC) - limits.window`.

El repositorio recibe `since` ya calculado, no la ventana: no debe saber cuánto dura la cuota.

---

## 5. Dónde se engancha, y por qué ahí

Dentro del span de la traza, **después de los atributos y antes del `match`**:

```python
span.set_attribute("command", command.name if command is not None else "none")

blocked = await self._quota_message(ctx, chat_id, command)
if blocked is not None:
    span.set_attribute("quota_blocked", True)
    await self._send(chat_id, message_thread_id, blocked)
    return

match command:
```

**Antes del `match`, no dentro.** `case Commands.INTERVIEW` arranca llamando a `restart_interview()`,
que borra mensajes, perfil y sesión. Cortar después sería lo peor de ambos mundos: destruir el
historial del usuario y acto seguido negarle el servicio. Hay un test que fija esta garantía.

**Dentro del span, no antes.** Un turno bloqueado sigue siendo un turno y debe verse en las trazas
con su `chat_id` y su comando. El atributo `quota_blocked` solo se emite cuando hay corte, así que en
Tempo se filtra por su presencia.

**Después de la limpieza de texto.** Los mensajes vacíos o de solo emojis ya han salido antes; no
gastan modelo, así que ni consumen cuota ni provocan una query.

El turno bloqueado **devuelve 200** a Telegram. Cualquier otra cosa provocaría reintentos.

---

## 6. Lo que este diseño no garantiza

**El tope se rebasa por un turno.** Consecuencia de comprobar antes de gastar, y la razón de ser del
margen de la sección 1. Cerrarlo del todo exigiría reservar tokens antes de llamar y liquidar
después: el doble de escrituras y un estado intermedio que limpiar si la llamada falla, para
ahorrar unos céntimos en el peor caso.

**Un límite duro es duro.** Si un chat agota el 100 % en mitad de una entrevista, se corta ahí. No se
debe añadir lógica especial para «entrevista en curso»: sería exactamente el hueco por el que se
escaparía un abuso. Lo que controla ese riesgo es el hueco entre `soft` y el límite.

**Cada mensaje bloqueado genera una respuesta.** Quien insista recibe un mensaje por intento. No hay
llamada al modelo, así que el coste es despreciable, y el límite de Telegram de un mensaje por
segundo y chat —con el `RetryAfter` que ya maneja `_send`— acota el resto.

**La bolsa es común.** `/interview` y el texto libre consumen del mismo contador; el comando solo
elige el umbral. Separarlos exigiría una columna `command` en `token_usage` y propagar el comando
hasta `record_token_usage`.

---

## 7. Añadir un comando nuevo

1. Añádelo a `Commands` en [domain/telegram.py](../src/fitcoach/domain/telegram.py).
2. Añádelo a `COMMAND_TIERS` con su nivel.

El paso 2 no es opcional: `limit_for()` indexa el diccionario con corchetes, así que un comando sin
nivel lanza `KeyError` en vez de colarse sin cuota. El test
`test_every_command_has_an_assigned_tier` lo detecta antes de llegar a producción.

Si el comando nuevo es tan caro como una entrevista, dale `SOFT`. Si es una conversación normal,
`HARD`. `UNLIMITED` solo para los que no invocan al modelo.

---

## 8. Tests

| Archivo | Qué cubre |
|---|---|
| [test_rate_limiter.py](../tests/unit_test/test_rate_limiter.py) | La política: cobertura del mapa, qué umbral aplica a cada comando, que lo caro nunca caiga después que lo barato, y que un comando sin nivel falle en alto. |
| [test_settings.py](../tests/unit_test/test_settings.py) (`TestUsageSettings`) | La calibración: derivación del umbral blando, ratio `1.0`, arranque sin configurar nada y rechazo de valores que anularían la cuota. |
| [test_conversation_service.py](../tests/unit_test/test_conversation_service.py) (`TestUsageQuota`) | El comportamiento: deja pasar por debajo, corta en cada umbral, **no llama a `restart_interview` al bloquear**, el texto libre sigue entre ambos umbrales, el `WARNING` con la causa, y que la ventana consultada sea la configurada y tz-aware. |

---

## Referencias

- Variables de entorno: [how-to.md](how-to.md#cuota-de-consumo-por-chat)
- Esquema de `token_usage`: [modelo-datos.md](modelo-datos.md)
- Consultas de consumo y coste: [queries-reference.md](queries-reference.md)
