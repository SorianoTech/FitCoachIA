# rag-doc: preguntas a la documentación por texto y voz

`infra/rag-doc/` es una web pública (PWA) que responde preguntas sobre una **lista blanca** de
ficheros `.md` de `docs/` e `infra/`. Es independiente de la app de FitCoachIA: tiene su propio
Compose, imagen y ciclo de vida. Dominio previsto: `https://faq.fitcoach.sergiosoriano.es`.

## Arquitectura

```
Navegador (PWA) ──HTTPS──> Nginx Proxy Manager ──> rag-doc (FastAPI, :8200)
                                                     ├─ embeddings: multilingual-e5-base (en la imagen)
                                                     ├─ Qdrant (red privada rag-internal)
                                                     ├─ LLM: API compatible con OpenAI vía LangChain
                                                     ├─ STT: API en la nube (gpt-4o-mini-transcribe) + faster-whisper local de respaldo
                                                     └─ TTS: Piper (es_ES-davefx-medium)
```

Todo es código abierto salvo el LLM, que es una API externa compatible con OpenAI (OpenRouter por
defecto) con un modelo abierto. Las llamadas al LLM usan `langchain_openai.ChatOpenAI`.

| Fichero | Responsabilidad |
|---|---|
| `rag_doc/main.py` | App FastAPI, lifespan (falla rápido sin `RAG_LLM_API_KEY`) y montaje de la PWA |
| `rag_doc/api.py` | `POST /api/ask`, `/api/stt`, `/api/tts` |
| `rag_doc/service.py`, `prompt.py`, `llm.py` | Recuperación + prompt con citas + llamada al LLM |
| `rag_doc/limits.py` | Rate limit por IP y tope diario |
| `rag_doc/voice.py` | Adaptadores de Whisper y Piper |
| `rag_doc/sources.py`, `chunking.py`, `embeddings.py`, `store.py`, `indexer.py` | Ingesta e índice en Qdrant |
| `rag_doc/static/` | PWA: `index.html`, `app.js`, `sw.js`, `manifest.json`, `offline.html`, iconos |
| `sources.yml` | Lista blanca de documentos indexables |
| `make_icons.py` | Regenera los iconos PNG (solo librería estándar) |

## Ingesta

La lista blanca está en `infra/rag-doc/sources.yml` y contiene los 31 `.md` de `docs/` salvo `docs/plan/` y
`docs/todo/` (notas de diseño y backlog). Un documento nuevo en `docs/` no se indexa hasta añadirlo a mano
(solo `.md`; los demás formatos, como `.drawio`, se rechazan). Solo el servicio `indexer` (perfil `index`) monta
`docs/` e `infra/` en solo lectura; el servicio web público no monta nada del repositorio.

```bash
make rag-index
```

- Los ficheros se trocean por encabezados (máx. `RAG_CHUNK_MAX_CHARS`, 1200 por defecto).
- Los ids de los puntos son `uuid5(fichero#índice)`: reindexar es idempotente y elimina los
  fragmentos de ficheros que salgan de la lista blanca.
- Si cambia la dimensión del modelo, la colección se recrea.
- Reindexa después de cambiar la documentación o `sources.yml`.

## Modelo de embeddings

`intfloat/multilingual-e5-base` (768 dimensiones), con prefijos `query:` / `passage:`. En una prueba
offline de 7 consultas acertó 7/7 en el top 5 (e5-small, 6/7). Si cambias el modelo hay que
reconstruir la imagen (el modelo va dentro), ajustar `RAG_EMBEDDING_MODEL`/`RAG_EMBEDDING_DIMENSIONS`
y reindexar. Ningún umbral de puntuación separa bien las preguntas fuera de tema, por eso
`RAG_MIN_SCORE` vale 0 y es el prompt del sistema el que decide responder "no aparece en la
documentación".

Los prompts están en `rag_doc/texts.py`. El del sistema exige respuestas breves, citas `[n]` solo de
fragmentos existentes (`[1][3]` si hay varias), indicar lo que falta si la respuesta es parcial, pedir
aclaración si la pregunta es ambigua, y trata contexto y pregunta como datos (anti-inyección). El de
reescritura nunca responde la pregunta y la deja igual si ya es autónoma o cambia de tema.

## Ver los chunks que recupera una pregunta

```bash
docker exec -i rag-doc python - "¿cómo funciona el scheduler?" < infra/rag-doc/eval/show_chunks.py
docker exec -i rag-doc python - "pregunta" --top-k 10 --full < infra/rag-doc/eval/show_chunks.py
```

`infra/rag-doc/eval/show_chunks.py` embebe la pregunta y consulta el Qdrant real con la configuración del
servicio; no llama al LLM. Imprime, por chunk, el puesto, la puntuación, `fichero — sección` y el texto
(`--full` lo muestra entero, `--top-k` cambia `RAG_TOP_K`) e indica si supera `RAG_MIN_SCORE`. Usa la
pregunta tal cual: no aplica la reescritura de preguntas de seguimiento. Requiere el servicio levantado
(`make rag-up`) y el corpus indexado (`make rag-index`).

## Evaluación de retrieval

```bash
make rag-eval                          # las 6 variantes de troceado
make rag-eval ARGS="--variants min300" # solo algunas (separadas por comas)
```

`infra/rag-doc/eval/retrieval_eval.py` re-embebe todo el corpus por variante en CPU. Sin límites
satura los núcleos y la RAM y puede bloquear el servidor, por eso corre en el servicio `evaluator`
(perfil `eval`) con `cpus: 2`, `mem_limit: 3g` y 2 hilos de torch (`EVAL_THREADS`, `--threads`).
No necesita Qdrant ni LLM. Evita lanzarlo en el servidor de producción mientras atiende tráfico.
Al terminar guarda el resultado en `infra/rag-doc/eval/results/<fecha>_<modelo>.json` (ignorado por git) con
proveedor, modelo, dimensiones y las métricas y parámetros de cada variante; además lo imprime
por consola. Usa el mismo proveedor de embeddings que el servicio (`RAG_EMBEDDING_PROVIDER`), así
que con `openai` el corpus completo se envía a la API una vez por variante.

### Cómo interpretar la salida

| Columna | Significado |
|---|---|
| `chunks` | Fragmentos que genera la variante (tamaño del índice) |
| `h@1`, `h@3`, `h@5` | Fracción de preguntas del tema cuyo fragmento correcto está en el top 1, 3 o 5 |
| `mrr` | Media de 1/posición del primer acierto (1 = siempre primero) |
| `minOn` (`top_on` en el JSON) | Mejor puntuación más baja entre las preguntas del tema |
| `maxOff` (`top_off` en el JSON) | Mejor puntuación más alta entre las preguntas fuera de tema |

Criterios para ajustar la precisión:

- `h@5` es lo que realmente ve el LLM (`RAG_TOP_K=5`): si el acierto está en el top 5, puede
  responder. `h@1` y `mrr` miden cuánto de directo llega el dato.
- Si `h@5` es alto y `h@1` bajo, sube `RAG_TOP_K` o añade un reranker antes de tocar el troceado.
- Si un mismo caso falla en todas las variantes, el problema es el corpus (falta contenido en
  `sources.yml`) o el `heading` del gold set, no el troceado.
- Los fragmentos grandes diluyen el significado y bajan `h@1`; los pequeños suben `chunks` y ruido.
  Prueba tamaños intermedios (600-1000 caracteres) añadiendo variantes a `VARIANTS`.
- Si `minOn` < `maxOff`, ninguna puntuación separa preguntas del tema de las de fuera de tema:
  `RAG_MIN_SCORE` no sirve de filtro y decide el prompt del sistema.
- Con pocos casos una diferencia de un solo acierto es ruido (con 24 preguntas, 0,042); amplía
  `gold_set.jsonl` antes de fiarte de décimas. Hoy tiene 69 casos (61 del tema, repartidos por 11
  documentos de la lista blanca con preguntas reformuladas, y 8 fuera de tema). Cada caso del tema lleva
  `source` y `heading` (basta con que aparezcan en el fragmento) y `facts` orientativos; los fuera de
  tema llevan `"offtopic": true`. El eval solo embebe `question` y no usa `history`. Los resultados
  guardados antes de la ampliación no son comparables con los nuevos.
- Compara siempre `local` y `openai` con la misma tabla antes de cambiar de proveedor.

Ejemplo (`text-embedding-3-small`, 27 casos: 24 del tema y 3 fuera de tema):

| Variante | chunks | h@1 | h@3 | h@5 | mrr |
|---|---|---|---|---|---|
| base (1200/0/0) | 229 | 0,708 | 0,833 | 0,917 | 0,797 |
| min300 | 221 | 0,667 | 0,833 | 0,917 | 0,779 |
| 800/min250 | 321 | 0,708 | 0,917 | 0,917 | 0,820 |
| 1600/min400 | 180 | 0,583 | 0,875 | 0,875 | 0,739 |

`800/min250` fue la mejor (sube `h@3` y `mrr`); el solape no aportó nada, y `h@5` se quedó en
0,917 en casi todas porque falla siempre el mismo caso. Aquí `minOn` (0,415) < `maxOff` (0,466).

## API

| Endpoint | Entrada | Salida |
|---|---|---|
| `POST /api/ask` | `{question (≤500), history (≤6 turnos, ≤1000 car. cada uno)}` | `{answer, sources[{number, source, heading, score}]}` |
| `POST /api/stt` | audio crudo (`Content-Type: audio/*`, ≤2 MB y ≤30 s) | `{text}` |
| `POST /api/tts` | `{text (≤3000)}` | `audio/wav` |
| `GET /health` | — | `{"status": "ok"}` |

Errores: `422` entrada no válida, `413` audio demasiado grande o largo, `415` tipo no soportado,
`429` límite superado, `502` LLM no disponible.

Cada fuente lleva `number`: la posición (desde 1) del pasaje en el contexto enviado al LLM, que es el `[n]`
que cita en la respuesta. No se deduplican: hay una fuente por pasaje usado. El front muestra cada chip como
`[n] fichero › sección` y convierte los `[n]` de la respuesta que tengan fuente en botones que resaltan su chip.

## Anti-abuso

- **Rate limit por IP**: `RAG_RATE_LIMIT_PER_MINUTE` peticiones por minuto (ventana deslizante);
  responde `429` con `Retry-After`.
- **Tope diario global**: `RAG_DAILY_CALL_CAP` peticiones a `/api/*` al día (protege el gasto del LLM).
- **IP del cliente**: con `RAG_TRUST_PROXY_HEADERS=true` se usa la última entrada de
  `X-Forwarded-For`, la que añade el proxy NPM. Si expones el puerto sin proxy, ponlo a `false`.
- Los contadores viven en memoria: se reinician al reiniciar el contenedor y no se comparten entre
  réplicas (el despliegue es de una sola instancia).
- Los límites de tamaño de pregunta, historial, audio y texto TTS están en `rag_doc/texts.py`.

## Voz

El navegador graba con `MediaRecorder`, envía el audio a `/api/stt` y lanza la pregunta con el texto
obtenido; cada respuesta tiene un botón "Escuchar" que pide el audio a `/api/tts`. El mismo botón se
convierte en "Parar" mientras suena (o se prepara) y al pulsarlo corta el audio y cancela la
petición; solo suena una respuesta a la vez. La transcripción usa por defecto una API en la nube (rápida y más precisa); si falla, recurre a Whisper local. Whisper (`small`,
int8, CPU) y la voz de Piper van **dentro de la imagen** y en ejecución `HF_HUB_OFFLINE=1`, así que
el arranque no depende de la red. Cambiar `RAG_STT_MODEL` exige reconstruir la imagen. El micrófono
solo funciona con HTTPS (o `localhost`).

## PWA

Servida por FastAPI desde `rag_doc/static/`, sin paso de build. Diseño de chat con tema índigo,
modo oscuro automático, pantalla de bienvenida con preguntas sugeridas y adaptada a móvil. El service worker precachea el shell,
usa red primero para la navegación (con `offline.html` de respaldo) y **nunca cachea `/api/*`**.
**Sube `CACHE_VERSION` en `sw.js` cada vez que cambies ficheros estáticos.** En iOS no hay
`beforeinstallprompt`: se instala desde Compartir → "Añadir a pantalla de inicio".

## Despliegue

```bash
cp infra/rag-doc/.env.rag-doc.example infra/rag-doc/.env   # y rellena RAG_LLM_API_KEY
make rag-up        # Qdrant + web (127.0.0.1:8200)
make rag-index     # primera indexación
make rag-logs
make rag-down      # conserva el volumen del índice
```

El servicio `rag-doc` se une a la red externa `proxy-network`; el proxy lo alcanza por nombre de
contenedor y puerto `8200`. Qdrant solo está en la red privada `rag-internal`.

En Nginx Proxy Manager crea un Proxy Host para `faq.fitcoach.sergiosoriano.es` con
**Forward Hostname** `rag-doc`, **Forward Port** `8200`, certificado SSL (Let's Encrypt) y
"Force SSL". Sin HTTPS no funcionan ni el micrófono ni la instalación de la PWA.

## Variables de entorno

Todas con prefijo `RAG_`; plantilla en `infra/rag-doc/.env.rag-doc.example`.

| Variable | Por defecto | Descripción |
|---|---|---|
| `RAG_LLM_API_KEY` | — (obligatoria) | Clave de la API del LLM; sin ella el servicio no arranca |
| `RAG_LLM_BASE_URL` | `https://openrouter.ai/api/v1` | API compatible con OpenAI |
| `RAG_LLM_MODEL` | `meta-llama/llama-3.3-70b-instruct` | Modelo abierto |
| `RAG_LLM_TIMEOUT_SECONDS` / `RAG_LLM_MAX_TOKENS` / `RAG_LLM_MAX_RETRIES` | `30` / `600` / `2` | Llamada al LLM |
| `RAG_LLM_REASONING_EFFORT` | `default` | `minimal`/`low`/`medium`/`high` para modelos de razonamiento (p. ej. `gpt-5-nano-2025-08-07` con `RAG_LLM_BASE_URL=https://api.openai.com/v1`): se omite la temperatura. `default` = modelos normales |
| `RAG_EMBEDDING_MODEL` / `RAG_EMBEDDING_DIMENSIONS` | `intfloat/multilingual-e5-base` / `768` | Con `local` deben coincidir con la imagen; con `openai`, p. ej. `text-embedding-3-small` / `1536` |
| `RAG_EMBEDDING_PROVIDER` | `local` | `local` (E5 en CPU) o `openai` (API compatible con OpenAI). Al cambiarlo hay que reindexar (`make rag-index`) |
| `RAG_EMBEDDING_BASE_URL` / `RAG_EMBEDDING_TIMEOUT_SECONDS` | `https://api.openai.com/v1` / `30` | Solo con `openai` |
| `RAG_EMBEDDING_API_KEY` | vacío | Solo con `openai`; si está vacía usa `RAG_LLM_API_KEY` |
| `RAG_QDRANT_COLLECTION` | `rag_doc` | Colección |
| `RAG_TOP_K` / `RAG_MIN_SCORE` | `5` / `0.0` | Recuperación (se leen al arrancar; no requieren reindexar) |
| `RAG_QUERY_REWRITE` | `true` | Reescribe la pregunta antes de buscar (se lee al arrancar) |
| `RAG_CHUNK_MAX_CHARS` / `RAG_CHUNK_MIN_CHARS` / `RAG_CHUNK_OVERLAP` | `1200` / `0` / `0` | Troceado: tamaño máximo, mínimo (fusiona fragmentos pequeños) y solape. Se aplican al indexar: ejecuta `make rag-index` tras cambiarlos |
| `RAG_RATE_LIMIT_PER_MINUTE` | `10` | Peticiones por minuto y por IP |
| `RAG_DAILY_CALL_CAP` | `500` | Tope diario global |
| `RAG_TRUST_PROXY_HEADERS` | `true` | Confiar en `X-Forwarded-For` |
| `RAG_STT_MODEL` | `small` | Tamaño de Whisper local (reconstruir la imagen) |
| `RAG_STT_PROVIDER` | `cloud` | `cloud` (API + respaldo local) o `local` (solo Whisper) |
| `RAG_STT_CLOUD_MODEL` | `gpt-4o-mini-transcribe` | Modelo de transcripción en la nube (p. ej. `whisper-1`, `gpt-4o-transcribe`) |
| `RAG_STT_CLOUD_BASE_URL` | `https://api.openai.com/v1` | Endpoint OpenAI-compatible de transcripción |
| `RAG_STT_CLOUD_API_KEY` | vacío | Clave; si está vacía usa `RAG_LLM_API_KEY` |
| `RAG_STT_CLOUD_TIMEOUT_SECONDS` | `20` | Timeout de la llamada |
| `RAG_PORT` | `8200` | Puerto publicado en `127.0.0.1` |
| `RAG_LOG_LEVEL` | `INFO` | Nivel de log |

## Tests

```bash
.venv/bin/python -m pytest -o testpaths=tests/unit_test/rag_doc --no-cov -q
```

Están en `tests/unit_test/rag_doc/` (OK y KO): troceado, lista blanca, indexador, prompt/LLM,
`/api/ask`, límites, voz con modelos simulados y ficheros de la PWA. `store.py` (Qdrant) y los
modelos reales de Whisper/Piper no tienen test unitario; se verificaron a mano con contenedores.
Este código no entra en la cobertura del 80 % de `make tests`, que solo mide `src/fitcoach`.
