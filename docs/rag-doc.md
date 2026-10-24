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
                                                     ├─ STT: faster-whisper (small, CPU)
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

La lista blanca está en `infra/rag-doc/sources.yml`. Solo el servicio `indexer` (perfil `index`) monta
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

## API

| Endpoint | Entrada | Salida |
|---|---|---|
| `POST /api/ask` | `{question (≤500), history (≤6 turnos, ≤1000 car. cada uno)}` | `{answer, sources[{source, heading, score}]}` |
| `POST /api/stt` | audio crudo (`Content-Type: audio/*`, ≤2 MB y ≤30 s) | `{text}` |
| `POST /api/tts` | `{text (≤3000)}` | `audio/wav` |
| `GET /health` | — | `{"status": "ok"}` |

Errores: `422` entrada no válida, `413` audio demasiado grande o largo, `415` tipo no soportado,
`429` límite superado, `502` LLM no disponible.

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
obtenido; cada respuesta tiene un botón "Escuchar" que pide el audio a `/api/tts`. Whisper (`small`,
int8, CPU) y la voz de Piper van **dentro de la imagen** y en ejecución `HF_HUB_OFFLINE=1`, así que
el arranque no depende de la red. Cambiar `RAG_STT_MODEL` exige reconstruir la imagen. El micrófono
solo funciona con HTTPS (o `localhost`).

## PWA

Servida por FastAPI desde `rag_doc/static/`, sin paso de build. El service worker precachea el shell,
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
| `RAG_EMBEDDING_MODEL` / `RAG_EMBEDDING_DIMENSIONS` | `intfloat/multilingual-e5-base` / `768` | Deben coincidir con la imagen |
| `RAG_QDRANT_COLLECTION` | `rag_doc` | Colección |
| `RAG_TOP_K` / `RAG_MIN_SCORE` | `5` / `0.0` | Recuperación |
| `RAG_RATE_LIMIT_PER_MINUTE` | `10` | Peticiones por minuto y por IP |
| `RAG_DAILY_CALL_CAP` | `500` | Tope diario global |
| `RAG_TRUST_PROXY_HEADERS` | `true` | Confiar en `X-Forwarded-For` |
| `RAG_STT_MODEL` | `small` | Tamaño de Whisper (reconstruir la imagen) |
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
