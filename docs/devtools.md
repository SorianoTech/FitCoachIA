# Devtools: depuración offline del entrenador

Guía unificada de `src/fitcoach/devtools/`. Sirve para ajustar el `SKILL.md`, el
`system_prompt.txt` o el modelo del entrenador **sin Telegram ni BD de conversaciones**, repitiendo
ejecuciones sobre entradas fijas y comparando resultados.

Detalle complementario: [trainer-agent.md](trainer-agent.md) (agente),
[plan-evaluator.md](plan-evaluator.md) (reglas de puntuación) y
[evals/trainer/README.md](../evals/trainer/README.md) (casos del golden set).

## 1. Piezas

| Módulo | Función |
|---|---|
| `trainer_debug.py` | CLI de una ejecución: un perfil + un catálogo -> plan y artefactos. También renderiza el prompt y re-evalúa ejecuciones guardadas |
| `trainer_compare.py` | CLI que ejecuta todos los casos del golden set para el producto cartesiano de skills x modelos y genera un resumen comparativo |
| `trainer_runner.py` | Núcleo compartido: carga perfil/catálogo, construye la cadena con la variante, llama al modelo, evalúa y escribe artefactos |
| `recording_model.py` | Envoltorio del modelo que registra cada petición y respuesta cruda (incluida la reparación) y avisa cada 10 s mientras espera |

Una ejecución es función pura de (perfil, catálogo, variante de prompt/skill, modelo). La cadena
se construye en cada ejecución: los cambios en disco se aplican sin reiniciar nada. El código de
producción no se modifica; las devtools envuelven el modelo.

Usan la configuración `ia_*` del entorno de desarrollo y el modelo de **generación**
(`build_trainer_model`, incluidos `ia_trainer_generation_model`, `..._temperature` y
`..._reasoning_effort`). `--model`, `--temperature`, `--max-tokens` y `--timeout` los sobrescriben.

## 2. Requisitos y entorno

- Los targets del Makefile resuelven el entorno de desarrollo (`/etc/fitcoachia/dev/.env.dev` o
  `.env.dev` del repositorio como fallback; ver [Makefile.md](Makefile.md)). No hace falta Docker
  para el modo con catálogo congelado.
- Se necesita acceso al LLM (`ia_base_url`, `ia_token`, `ia_model`), salvo con `--render-only` y
  `--evaluate-run`, que no llaman al modelo.
- `--chat-id` requiere `database_url` (lee `interviewer_profiles`); `--live-retrieval` requiere
  `vector_database_url` y `embedder_url` apuntando a servicios en marcha.

## 3. Targets del Makefile

| Comando | Qué hace |
|---|---|
| `make trainer-debug ARGS="..."` | Ejecuta `python -m fitcoach.devtools.trainer_debug` |
| `make trainer-compare ARGS="..."` | Ejecuta `python -m fitcoach.devtools.trainer_compare` |
| `make trainer-refresh-catalogues` | Regenera el `catalogue.json` de cada caso con recuperación real (`--live-retrieval --save-catalogue --render-only`) |

## 4. `trainer_debug`: una ejecución

```bash
# Solo renderiza el prompt que se enviaría (sin LLM, sin coste)
make trainer-debug ARGS="--case-dir evals/trainer/cases/beginner_gym_lose_fat --render-only"

# Ejecución completa con una copia de la skill en edición
make trainer-debug ARGS="--case-dir evals/trainer/cases/knee_injury_home \
  --skills-root /tmp/skills --skill trainer --variant v2"

# Reproducir el caso real de un usuario
make trainer-debug ARGS="--chat-id 123 --live-retrieval --save-catalogue evals/trainer/catalogue_123.json"

# Re-puntuar una ejecución guardada sin llamar al modelo
make trainer-debug ARGS="--evaluate-run runs/trainer/<carpeta-de-ejecucion>"
```

| Opción | Uso |
|---|---|
| `--case-dir` | Carpeta con `profile.json` y `catalogue.json` |
| `--profile` / `--chat-id` | Perfil desde un JSON o desde la BD (excluyentes) |
| `--catalogue` / `--live-retrieval` | Catálogo congelado o recuperación real (excluyentes) |
| `--top-k` | Ejercicios por grupo muscular en la recuperación real (por defecto `ia_rag_top_k`) |
| `--save-catalogue` | Congela el catálogo usado |
| `--case` | Nombre del caso en los artefactos (por defecto, el nombre del perfil) |
| `--variant` | Etiqueta de la variante (por defecto `default`) |
| `--skill` | Carpeta de skill (por defecto `ia_trainer_skill`) |
| `--prompts-root` / `--skills-root` | Carpetas con `trainer/system_prompt.txt` y `<skill>/SKILL.md` alternativos |
| `--model` / `--temperature` / `--max-tokens` | Sobrescriben `ia_model`, `ia_temperature`, `ia_trainer_max_tokens` |
| `--timeout SECONDS` | Timeout por petición al LLM (entero positivo) |
| `--out` | Raíz de artefactos (por defecto `runs/trainer`) |
| `--render-only` | Escribe el prompt y los mensajes sin llamar al modelo |
| `--evaluate-run DIR` | Re-evalúa una ejecución guardada |
| `-v` / `--verbose` | Logging DEBUG |

Mientras espera, informa a stderr del inicio de cada llamada, las reparaciones y un aviso cada
10 s. No es streaming de tokens ni muestra el razonamiento del modelo. El timeout es por petición:
una reparación y los reintentos aumentan el total.

Código de salida: 0 si se generó un plan, 1 en otro caso. Con `--evaluate-run`, 0 si el plan no
tiene errores del evaluador y 1 si los tiene.

## 5. `trainer_compare`: variantes sobre el golden set

```bash
# Todos los casos con dos skills
make trainer-compare ARGS="--skill trainer --skill trainer-dev"

# Producto cartesiano de skills y modelos
make trainer-compare ARGS="--skill trainer --skill trainer-dev --model modelo-a --model modelo-b"
```

| Opción | Uso |
|---|---|
| `--cases-root` | Casos a ejecutar (por defecto `evals/trainer/cases`) |
| `--skill` / `--model` | Repetibles; cada combinación es una variante (por defecto, la configurada) |
| `--prompts-root` / `--skills-root` | Prompts y skills alternativos |
| `--temperature` / `--max-tokens` / `--timeout` | Igual que en `trainer_debug` |
| `--out` | Raíz (por defecto `runs/trainer-comparisons`) |
| `-v` / `--verbose` | Logging DEBUG |

Crea una carpeta fechada en `runs/trainer-comparisons/` con los artefactos de cada ejecución y
`comparison.md`, `.csv` y `.json`. Columnas del resumen: caso, variante, skill, modelo, estado,
`score`, errores y avisos del evaluador, tokens, latencia, llamadas, reparaciones y huella del
prompt. Devuelve 1 si alguna ejecución terminó en estado `error`.

Consume tokens: casos x variantes llamadas al LLM, como mínimo.

## 6. Artefactos de una ejecución

`runs/trainer/<fecha>-<caso>-<variante>/` (`runs/` está en `.gitignore`):

| Archivo | Contenido |
|---|---|
| `system_prompt.txt` | Prompt exacto enviado (skill y catálogo incluidos) |
| `calls/NN_request.json`, `calls/NN_response.txt` | Cada llamada, incluida la reparación |
| `plan.json`, `plan.md` | Turno validado y vista legible por semanas y días |
| `evaluation.json`, `evaluation.md` | Resultado del evaluador ([plan-evaluator.md](plan-evaluator.md)) |
| `run.json` | Estado, error, llamadas, tokens, latencia, `score`, `eval_errors`, `eval_warnings`, `prompt_fingerprint` |
| `profile.json`, `catalogue.json` | Entradas, para repetir la ejecución |

## 7. Flujo de trabajo recomendado

1. `--render-only` para revisar el prompt resultante tras editar la skill (gratis).
2. Un caso concreto con `trainer-debug` para ver el plan y los hallazgos.
3. `trainer-compare` sobre el golden set para confirmar que la variante no empeora `score`,
   errores, tokens ni latencia respecto a la base.
4. Tras cambiar reglas del evaluador, `--evaluate-run` re-puntúa ejecuciones antiguas sin coste.

Los catálogos del golden set son una foto de la recuperación; regenerarlos
(`make trainer-refresh-catalogues`) cambia el baseline. Ver advertencias en
[evals/trainer/README.md](../evals/trainer/README.md).

## 8. Alcance

Solo cubre el entrenador (generación). No hay devtools para el entrevistador, el curator ni las
consultas sobre el plan; esas rutas se prueban con los tests unitarios e IT.
