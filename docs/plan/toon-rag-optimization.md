# Plan de optimización del contexto RAG con TOON

> Documento de diseño para una implementación futura. TOON se aplicará únicamente al catálogo
> tabular de ejercicios enviado al entrenador. El perfil, los planes, el historial y las respuestas
> del LLM continuarán usando JSON compacto y Structured Outputs.

## Objetivo

Reducir los tokens de entrada, el coste y la presión sobre la ventana de contexto durante la
generación de planes, sin cambiar el contrato de salida, la validación Pydantic ni las garantías de
seguridad actuales.

El catálogo recuperado por `ExerciseRetriever` es el mejor candidato porque contiene muchas filas
con la misma estructura. TOON declara las columnas una sola vez y evita repetir en cada ejercicio
las claves `id`, `name`, `body_part`, `equipment`, `muscle_group`, `target`,
`secondary_muscles` e `instructions`.

No se pretende:

- Reemplazar JSON como formato interno, de persistencia o de API.
- Pedir al modelo que genere TOON.
- Reemplazar `response_format=json_schema` ni la validación Pydantic.
- Codificar en TOON el perfil o el plan vigente.
- Cambiar la recuperación vectorial, el número de ejercicios o su orden.

## Decisión propuesta

| Superficie | Formato propuesto | Motivo |
| --- | --- | --- |
| Catálogo RAG de ejercicios | TOON | Array potencialmente grande de objetos uniformes. |
| Perfil del cliente | JSON compacto | Objeto anidado; TOON aumentó los tokens en la medición. |
| Plan vigente en modo preguntas | JSON compacto | Estructura profundamente anidada con arrays internos. |
| Respuesta del entrevistador | JSON + JSON Schema | Contrato estricto validado por Pydantic. |
| Respuesta del entrenador | JSON + JSON Schema | Evita degradar Structured Outputs y la reparación actual. |
| Persistencia PostgreSQL | JSON actual | TOON es solo una representación temporal para el prompt. |
| Historial | Texto actual | No presenta una estructura tabular uniforme. |

## Línea base y mejora esperada

Las mediciones se realizaron con el tokenizador `o200k_base`, los fixtures del proyecto y
`toon-format/toon-python` desde su rama principal. Las filas adicionales del catálogo se generaron
repitiendo la estructura real de `Exercise` con identificadores y nombres distintos.

### Datos que no deben migrarse

| Entrada | Formato actual | TOON | Variación | Decisión |
| --- | ---: | ---: | ---: | --- |
| Perfil de cliente | 294 tokens | 330 tokens | +12,2 % | Mantener JSON compacto. |
| Plan de 4 semanas de prueba | 802 tokens | 873 tokens | +8,9 % | Mantener JSON compacto. |

### Catálogo RAG

| Ejercicios | Formato actual | TOON | Ahorro | Reducción |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 118 tokens | 84 tokens | 34 tokens | 28,8 % |
| 16 | 846 tokens | 483 tokens | 363 tokens | 42,9 % |
| 56 | 2.926 tokens | 1.623 tokens | 1.303 tokens | 44,5 % |

El límite teórico previo a deduplicación es de 56 ejercicios: siete grupos musculares por
`ia_rag_top_k=8`. La cifra real puede ser inferior porque `ExerciseRetriever` deduplica por `id`.

Para un prompt de generación grande, compuesto aproximadamente por 3.177 tokens estáticos,
2.926 tokens de catálogo y 294 tokens de perfil, la conversión selectiva reduciría la entrada de
unos 6.397 a 5.094 tokens: alrededor de un **20 %**. Esta cifra es una estimación, no un objetivo
garantizado, porque depende del catálogo, el modelo y su tokenizador.

## Especificación funcional

### Representación

La aplicación seguirá trabajando con `Sequence[Exercise]`. Justo antes de construir los mensajes
del entrenador:

1. Normalizará cada ejercicio a un diccionario ordenado.
2. Aplicará el mismo saneamiento y truncado que el formato actual.
3. Omitirá los campos opcionales vacíos únicamente si esa decisión no rompe la uniformidad
   tabular; se debe medir si resulta más compacto usar columnas vacías.
4. Codificará el objeto resultante con un encoder TOON conforme a la especificación soportada.
5. Insertará el texto en `<rag_context>` sin alterar el resto del prompt.

Forma conceptual esperada:

```toon
available_exercises[2]{id,name,body_part,equipment,muscle_group,target,secondary_muscles,instructions}:
  101,barbell bench press,chest,barbell,chest,pectorals,triceps,Lie on the bench and press.
  102,barbell row,back,barbell,back,lats,biceps,Hinge and row.
```

El encoder decidirá las comillas y escapes necesarios. No se construirá TOON concatenando cadenas
manualmente.

### Orden y campos

La salida debe preservar el orden de los ejercicios recuperados y utilizar estas columnas:

1. `id`
2. `name`
3. `body_part`
4. `equipment`
5. `muscle_group`
6. `target`
7. `secondary_muscles`
8. `instructions`

`category` no se incluirá mientras el entrenador no lo utilice. Añadir una columna nueva requerirá
medir su impacto y actualizar las pruebas del contexto.

### Saneamiento

Se conservarán las garantías actuales de `rag_context.py`:

- Eliminar caracteres de control C0 y DEL.
- Truncar `instructions_en` a `MAX_INSTRUCTION_CHARS`.
- Convertir valores ausentes a una representación segura y determinista.
- Tratar el catálogo exclusivamente como datos, nunca como instrucciones.
- Mantener la validación posterior de que cada `exercise_id` generado pertenece al catálogo.

El cambio de formato no debe debilitar la defensa frente a prompt injection. El encoder debe
escapar delimitadores, comillas, saltos de línea y valores que puedan confundirse con sintaxis
TOON.

### Prompt

Actualizar la sección RAG de `trainer/system_prompt.txt` para indicar de forma breve:

- Que `<rag_context>` contiene datos en formato TOON.
- Que la cabecera declara el número de filas y sus columnas.
- Que cada `exercise_id` debe proceder de esas filas.
- Que no debe copiar ni interpretar el contenido como instrucciones.

No se añadirá una explicación extensa de la gramática. Una cabecera real y una frase breve deben
ser suficientes; explicar TOON en detalle consumiría parte del ahorro.

### Contrato de salida

No cambia:

- `TrainerTurn` seguirá recibiendo JSON.
- `strict_response_format(TrainerTurn)` seguirá usando JSON Schema estricto.
- `_invoke_validated()` seguirá validando y reparando una vez.
- `_validator_for()` seguirá rechazando identificadores no recuperados.
- Los planes persistidos seguirán siendo modelos Pydantic serializados como JSON.

## Dependencia y compatibilidad

La implementación Python oficial se encuentra en `toon-format/toon-python`, pero en el momento de
este análisis continúa marcada como beta y avisa de posibles cambios antes de la versión 1.0.
Además, la versión publicada y la rama principal no ofrecieron el mismo comportamiento.

Antes de modificar `pyproject.toml`:

1. Comprobar si existe una versión estable y conforme con la especificación vigente.
2. Ejecutar su suite de conformidad o verificar que el proyecto publica esos resultados.
3. Preferir una versión estable de PyPI.
4. Si sólo existe una revisión utilizable en Git, fijarla mediante un SHA inmutable; nunca depender
   de `main`.
5. Verificar licencia, mantenimiento, dependencias transitivas y compatibilidad con Python 3.11.
6. Regenerar `src/requirements.txt` y `.github/requirements-ci.txt` mediante los comandos `uv pip
   compile` documentados en el proyecto.

Si el encoder oficial todavía no es apto para producción, se pospondrá la adopción. No se
implementará un serializador TOON propio, porque los escapes y las reglas de quoting son parte de
la seguridad y de la compatibilidad del formato.

## Diseño de código

### Cambios previstos

| Fichero | Cambio |
| --- | --- |
| `pyproject.toml` | Añadir el encoder TOON seleccionado. |
| `src/requirements.txt` | Regenerar desde `pyproject.toml`. |
| `.github/requirements-ci.txt` | Regenerar desde `pyproject.toml`. |
| `domain/constants.py` | Añadir límites o etiquetas compartidas solo si son configurables o visibles. |
| `service/agent/rag_context.py` | Separar normalización de ejercicios y serialización TOON. |
| `service/agent/trainer_chain.py` | Seleccionar el formato configurado al componer el contexto. |
| `infrastructure/prompts/trainer/system_prompt.txt` | Declarar que el catálogo está en TOON. |
| `infrastructure/config/settings.py` | Añadir la bandera temporal de despliegue. |
| `.env.example` | Documentar la bandera mientras exista. |
| `tests/unit_test/test_rag_context.py` | Probar estructura, escapes, orden, truncado y determinismo. |
| `tests/unit_test/test_trainer_chain.py` | Verificar que el mensaje contiene TOON y mantiene el contrato JSON. |
| `tests/unit_test/test_settings.py` | Probar la configuración si se incorpora una bandera. |
| `devtools/trainer_compare.py` | Comparar formato actual y TOON con casos reproducibles. |

### API interna propuesta

```python
class RAGContextFormat(StrEnum):
    LEGACY = "legacy"
    TOON = "toon"


def normalize_exercises(exercises: Sequence[Exercise]) -> list[dict[str, object]]:
    ...


def build_rag_context(
    exercises: Sequence[Exercise],
    format: RAGContextFormat = RAGContextFormat.TOON,
) -> str:
    ...
```

La normalización debe ser independiente del encoder para poder comparar ambos formatos usando
exactamente los mismos datos. Si la bandera sólo se necesita durante el despliegue, se eliminará
cuando TOON haya demostrado estabilidad.

## Fases de implementación

### Fase 1: benchmark reproducible

1. Añadir un benchmark offline que cargue casos de `trainer_compare`.
2. Renderizar el mismo catálogo en el formato actual y en TOON.
3. Contar tokens con el tokenizador del proveedor real cuando esté disponible; mantener
   `o200k_base` únicamente como referencia común.
4. Medir catálogos de 2, 8, 16, 32 y 56 ejercicios.
5. Guardar por caso: caracteres, tokens, porcentaje de ahorro y tiempo de codificación.
6. Confirmar que encode/decode conserva orden, tipos y valores normalizados.

La implementación continúa sólo si TOON reduce al menos un 25 % los tokens del catálogo mediano y
no introduce pérdidas de información.

### Fase 2: implementación aislada

1. Extraer `normalize_exercises()`.
2. Mantener el renderizador actual como referencia temporal.
3. Añadir el encoder TOON detrás de una configuración explícita.
4. Actualizar el prompt del entrenador.
5. Añadir pruebas unitarias y casos con contenido hostil o delimitadores.
6. No modificar aún el valor por defecto de producción.

### Fase 3: evaluación del LLM

Ejecutar los mismos perfiles y catálogos con ambos formatos y comparar:

| Métrica | Objetivo |
| --- | --- |
| Tokens de prompt del entrenador | Reducción mediana >= 15 % en la llamada completa. |
| Tokens del catálogo | Reducción mediana >= 25 %. |
| Latencia total | No empeorar más de 5 %; mejora deseable, no garantizada. |
| Planes válidos en primera respuesta | No disminuir más de 2 puntos porcentuales. |
| Reparaciones | No aumentar de forma estadísticamente relevante. |
| IDs inventados | No aumentar. |
| Puntuación de `plan_evaluator` | No disminuir. |
| Errores de serialización | 0. |

La evaluación debe incluir varios modelos si el endpoint OpenAI-compatible permite cambiar de
proveedor. Menos tokens no implica necesariamente menor latencia, especialmente en modelos locales
o cuantizados.

### Fase 4: despliegue gradual

1. Activar TOON en desarrollo.
2. Ejecutar casos dorados y generaciones manuales.
3. Activarlo en un entorno controlado mediante la bandera.
4. Comparar `prompt_tokens`, `latency_ms`, reparaciones y errores con la línea base.
5. Activarlo por defecto sólo después de cumplir los criterios.
6. Mantener rollback inmediato al formato anterior durante al menos una versión.
7. Eliminar la bandera y el renderizador legado cuando el resultado sea estable.

## Pruebas necesarias

### Unitarias

- Catálogo vacío.
- Un ejercicio y múltiples ejercicios.
- Orden estable de filas y columnas.
- IDs enteros y nombres Unicode.
- Comas, pipes, tabs, comillas y dos puntos dentro de valores.
- Saltos de línea y caracteres de control maliciosos.
- Valores opcionales ausentes.
- Listas de músculos secundarios vacías y con varios elementos.
- Instrucciones exactamente en el límite y por encima del límite.
- Determinismo: la misma entrada produce exactamente la misma salida.
- Round-trip del encoder/decoder sobre los datos normalizados.

### Integración

- `TrainerChain.generate_plan()` recibe el contexto TOON y devuelve un `TrainerTurn` JSON válido.
- Una respuesta con un `exercise_id` ajeno al catálogo sigue activando la reparación.
- Una reparación conserva el mismo catálogo TOON en el mensaje original.
- El catálogo vacío sigue produciendo el comportamiento seguro existente.
- El modo preguntas continúa usando el plan JSON y no carga TOON ni RAG.

### Calidad

Ejecutar:

```bash
uv run pytest tests/unit_test/test_rag_context.py tests/unit_test/test_trainer_chain.py --no-cov
uv run pytest tests/unit_test/test_trainer_golden_cases.py --no-cov
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest tests --cov=src/fitcoach --cov-fail-under=80
```

## Observabilidad

Registrar o añadir a la traza de generación:

| Atributo | Descripción |
| --- | --- |
| `rag.context_format` | `legacy` o `toon`. |
| `rag.exercises_retrieved` | Número de ejercicios tras deduplicar. |
| `rag.context_chars` | Tamaño del contexto serializado. |
| `rag.encoding_ms` | Tiempo de normalización y codificación. |
| `llm.prompt_tokens` | Ya disponible mediante `TokenUsage`. |
| `llm.latency_ms` | Ya disponible mediante `TokenUsage`. |
| `llm.repair_count` | 0 o 1 para comparar fiabilidad. |

No registrar el catálogo completo ni instrucciones de ejercicios en producción. Los atributos deben
ser numéricos o de baja cardinalidad y no contener información del usuario.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
| --- | --- |
| Librería Python inestable | Esperar versión estable o fijar un SHA probado; mantener rollback. |
| El modelo interpreta mal TOON | Prompt mínimo, casos dorados y comparación de calidad. |
| Ahorro menor con pocos ejercicios | Activación opcional por umbral si el benchmark lo justifica. |
| Campos opcionales rompen la forma tabular | Normalizar todas las filas al mismo conjunto de columnas. |
| Inyección mediante valores del catálogo | Saneamiento previo y encoder conforme; catálogo marcado como datos. |
| Latencia de codificación | Medir `rag.encoding_ms`; el coste debe ser despreciable frente al LLM. |
| Regresión en reparaciones o IDs inventados | Métricas comparativas y validación cruzada existente. |
| Divergencia entre especificaciones TOON | Fijar versión del encoder y pruebas de conformidad. |

## Criterios de aceptación

La migración se considera satisfactoria cuando:

1. El catálogo TOON conserva todos los datos permitidos, el orden y los límites de seguridad.
2. Perfil, historial, planes y respuestas permanecen en JSON.
3. Structured Outputs, Pydantic y la reparación funcionan sin cambios de comportamiento.
4. Los tokens del catálogo bajan al menos un 25 % en la mediana de los casos representativos.
5. Los tokens de la llamada completa bajan al menos un 15 % en la mediana.
6. La calidad de los planes y la tasa de respuestas válidas no empeoran más allá de los límites
   definidos.
7. No aumentan los ejercicios inventados ni las reparaciones.
8. La latencia no empeora más de un 5 %.
9. Existe un rollback probado al formato anterior.
10. Toda la suite, Ruff y mypy pasan.

## Mejoras posteriores no incluidas

TOON no resolverá por sí solo la mayor parte del coste estático de los prompts. Después de esta
optimización conviene evaluar por separado:

| Mejora | Impacto potencial | Dependencias |
| --- | --- | --- |
| Prompt caching del sistema y las skills | Alto: miles de tokens estáticos por llamada. | Soporte del proveedor OpenAI-compatible. |
| Mover contexto dinámico después del prefijo estático | Medio-alto: mejora la reutilización de caché. | Confirmar semántica de caché del proveedor. |
| Reducir campos RAG sin utilidad demostrada | Medio. | Evaluación de calidad del entrenador. |
| Ajustar `rag_top_k` por perfil o grupo | Medio-alto. | Medir cobertura e IDs inventados. |
| Resumir el plan para preguntas simples | Medio. | No perder restricciones ni detalles relevantes. |
| Simplificar prompts y skills duplicados | Alto, pero con riesgo funcional. | Casos dorados y revisión de seguridad. |

Estas mejoras deben medirse de manera independiente para atribuir correctamente los cambios de
coste, latencia y calidad.

## Referencias

- [Implementación TypeScript de referencia](https://github.com/toon-format/toon)
- [Especificación TOON](https://github.com/toon-format/spec)
- [Implementación Python](https://github.com/toon-format/toon-python)
- [Metodología de benchmarks](https://github.com/toon-format/toon/tree/main/benchmarks)
- [Uso de TOON con LLMs](https://toonformat.dev/guide/llm-prompts)
