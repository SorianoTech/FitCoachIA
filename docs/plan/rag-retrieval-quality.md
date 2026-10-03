# Plan de evaluación de la calidad de recuperación RAG

> Documento de diseño para una implementación futura. Primero se medirá la recuperación actual
> sin cambiar su comportamiento. La similitud de coseno será un diagnóstico y, solo si los datos
> lo justifican, servirá para calibrar un umbral de aceptación.

## Actualización de implementación

Ya se han aplicado correcciones de coherencia: grupos canónicos derivados de `target`,
disponibilidad compartida de equipamiento, alias de bandas y consultas con significado
alineado con el corpus. Se han añadido `ExerciseMatch`, `search_scored()` y
`retrieve_traced()` con distancia, similitud, filtros y ranking por grupo.
`retrieve()` reutiliza esa ruta; el catálogo final sigue deduplicado por ID.
El orden en empates es estable por ID.

No se han implementado etiquetas, runner de métricas, umbral ni comparación de relevancia.
El comportamiento descrito en «Situación actual» más abajo corresponde al baseline
histórico anterior a estas correcciones. Los catálogos congelados del entrenador se
conservan como referencia histórica, no como resultados de la recuperación nueva.
Antes de comparar calidad hay que obtener una nueva línea base y completar etiquetas;
no se afirma una mejora cuantificada de relevancia.

## Objetivo

Determinar si el catálogo recuperado permite construir un plan adecuado para el perfil y
distinguir tres problemas:

1. El corpus no contiene ejercicios adecuados.
2. El recuperador no encuentra o no prioriza los ejercicios adecuados que sí existen.
3. El entrenador genera un mal plan pese a disponer de un buen catálogo.

La evaluación principal será determinista sobre resultados etiquetados por personas. La calidad
del plan generado se medirá por separado con el evaluador existente. No se usará la valoración de
un LLM como sustituto de la referencia humana ni como garantía de seguridad.

## Situación actual

| Superficie | Comportamiento actual |
| --- | --- |
| `service/agent/exercise_retriever.py` | Hace una consulta por cada uno de siete grupos musculares, recupera `top_k` por consulta y deduplica por identificador preservando el orden de aparición. |
| `service/agent/rag_context.py` | Construye consultas con grupo, objetivo, equipamiento y entorno; aplica listas de equipamiento por entorno. |
| `infrastructure/vectordb/pgvector_exercise_repository.py` | Filtra por equipamiento cuando corresponde y ordena por distancia coseno, pero devuelve ejercicios sin sus distancias. |
| `repository/exercise_repository.py` | El contrato de `search()` devuelve `list[Exercise]`, sin puntuaciones ni información de ranking. |
| `evals/trainer/` | Contiene perfiles ficticios y catálogos congelados para comparar el entrenador. Estos catálogos no son etiquetas de relevancia. |
| `service/agent/plan_evaluator.py` | Informa de grupos ausentes en el catálogo y evalúa reglas del plan; no mide Precision@k ni Recall@k del recuperador. |
| `devtools/trainer_debug.py` | Permite recuperar un catálogo real y congelarlo para probar el entrenador. |

Aspectos que la evaluación debe hacer visibles, sin corregirlos antes de obtener una línea base:

- El grupo muscular se expresa en el texto de consulta, no como filtro SQL obligatorio.
- En casa se admiten equipos de una lista general, no exclusivamente los declarados en el perfil.
  En gimnasio no se aplica filtro de equipamiento.
- Las consultas actuales no incorporan explícitamente lesiones ni experiencia.
- La consulta usa `target` para el objetivo del usuario y `category` para el entorno; el loader
  construye esos campos con los valores del ejercicio. Compartir formato no garantiza compartir
  significado: habrá que contrastar este posible desajuste mediante experimentos.
- El catálogo final concatena y deduplica resultados de varias consultas. No constituye un ranking
  global de similitud.

## Alcance y principios

- Medir recuperación sin invocar al entrenador como requisito.
- Mantener inicialmente los ejercicios, su orden, el `top_k` y las respuestas de producción.
- No enviar perfiles reales, credenciales ni datos personales a los artefactos de evaluación.
- Versionar corpus, modelo de embeddings, consultas y etiquetas para comparar ejecuciones.
- Separar relevancia semántica, compatibilidad con restricciones y cobertura del catálogo.
- No interpretar una similitud alta como probabilidad de relevancia ni como aprobación clínica.
- No fijar un umbral universal como `0.7`: su utilidad debe demostrarse para esta configuración.

## 1. Construir una referencia etiquetada

### Casos y unidad de evaluación

Crear un conjunto independiente en `evals/retrieval/`. Reutilizar los perfiles ficticios de
`evals/trainer/cases/` como punto de partida, no sus catálogos como resultados esperados.

La unidad de ranking será `(case_id, muscle_group)`, porque así consulta el recuperador. Evaluar
también la unión deduplicada de resultados para cada perfil, que es lo que recibe el entrenador.
Reportar por separado grupos necesarios para el caso y grupos auxiliares; no exigir que cualquier
perfil necesite cardio o todos los grupos por igual.

Empezar con 20-30 perfiles ficticios variados, como propuesta de piloto, no como garantía de
suficiencia estadística:

- Gimnasio, casa y exterior, con diferencias explícitas de equipamiento disponible.
- Principiantes y personas con experiencia; objetivos y tiempos de sesión distintos.
- Restricciones explícitas de movimiento y casos con lesiones revisados por una persona
  cualificada.
- Casos con muchas alternativas, pocas alternativas y ninguna alternativa válida en el corpus.
- Consultas donde sea fácil confundir grupos, equipos o variantes de un mismo ejercicio.

### Etiquetas por ejercicio

Para cada consulta, guardar etiquetas por `exercise_id` con este esquema conceptual:

| Campo | Contenido |
| --- | --- |
| `relevance` | `0`: no relevante; `1`: alternativa secundaria; `2`: relevante; `3`: especialmente adecuada. |
| `eligible` | `true`, `false` o `null` si todavía no puede determinarse la compatibilidad. |
| `constraint_reasons` | Motivos estructurados: equipo no disponible, restricción de movimiento, etc. |
| `rationale` | Justificación breve de la etiqueta y de los casos dudosos. |

La rúbrica debe definir qué significa cada grado para un perfil y grupo concreto. Para las
métricas binarias, considerar positivo `relevance >= 2` y `eligible = true`. Para nDCG usar el grado
de relevancia, con ganancia cero cuando el ejercicio no sea elegible. Reportar los casos sin juicio
de compatibilidad como pendientes, no como seguros.

No etiquetar automáticamente como inseguro un ejercicio por una palabra en su nombre o una lesión
genérica. Las heurísticas pueden proponer candidatos para revisión, pero las restricciones de
salud requieren contexto y revisión cualificada.

### Obtención de candidatos y cobertura de etiquetas

1. Inspeccionar el corpus para localizar ejercicios apropiados, independientemente del ranking.
2. Crear un pool con resultados del baseline, variantes de consultas y filtros, a mayor profundidad
   que el máximo `k` evaluado, más candidatos encontrados manualmente y negativos difíciles.
3. Etiquetar sin mostrar puntuaciones ni variante de origen para reducir sesgos.
4. Revisar desacuerdos y una muestra de etiquetas con una segunda persona.
5. Congelar etiquetas y registrar si la revisión fue exhaustiva o limitada al pool.

Un resultado no etiquetado no equivale a un negativo: el runner informará de `judged@k` y marcará
como incompletas las métricas que dependan de esos juicios. Completar las etiquetas antes de
comparar variantes sobre resultados nuevos.

El Recall@k real exige conocer todos los positivos del corpus. Cuando solo exista un pool,
denominar la métrica `Recall@k (pool)` y declarar que es una aproximación; no presentarla como recall
global. Para los casos sin positivos confirmados, distinguir ausencia real en un corpus revisado
de referencia incompleta.

### División de los datos

Separar conjuntos de desarrollo, calibración y prueba antes de optimizar. Mantener perfiles
equivalentes o variantes del mismo caso en la misma partición para evitar fuga de información.

Usar desarrollo para modificar consultas y filtros, calibración para seleccionar umbrales y prueba
para la comparación final. No elegir parámetros con el conjunto de prueba. Con un piloto pequeño,
reportar la incertidumbre y ampliar los casos antes de activar filtros en producción.

## 2. Instrumentar los resultados sin alterar la recuperación

Introducir una representación tipada de coincidencia con ejercicio, distancia coseno y similitud.
Calcular en PostgreSQL la distancia que se usa para ordenar y seleccionarla junto con el registro,
sin volver a generar embeddings.

Para pgVector:

```text
cosine_distance = 1 - cosine_similarity
cosine_similarity = 1 - cosine_distance
```

La similitud teórica está entre `-1` y `1`, y la distancia entre `0` y `2`. No tratar la similitud como
un porcentaje ni aplicar transformaciones que oculten sus valores originales. Validar puntuaciones
finitas y vectores válidos; un error de embedding o de consulta debe producir un fallo explícito de
ejecución, no una recuperación vacía presentada como correcta.

Propuesta de integración:

- Añadir `search_scored()` al contrato del repositorio y a su implementación.
- Hacer que `search()` reutilice esa búsqueda y extraiga los ejercicios, conservando su contrato.
- Extraer en el recuperador una única ruta de consulta con trazas y hacer que `retrieve()` siga
  devolviendo la misma lista deduplicada. El runner consumirá la ruta trazada.
- Compartir construcción de consultas, filtros y búsqueda entre evaluación y producción; evitar
  un segundo recuperador que pueda comportarse de otra manera.

Guardar por consulta:

| Dato | Uso |
| --- | --- |
| Texto de consulta y grupo solicitado | Auditar la intención y el formato. |
| Filtro aplicado y configuración | Reproducir qué candidatos podían aparecer. |
| ID, posición, metadatos, distancia y similitud | Evaluar ranking y compatibilidad. |
| Lista antes de deduplicar y catálogo final | Detectar repetición entre grupos y pérdida de variedad. |
| Tiempo de embedding y búsqueda | Separar calidad y coste operativo. |
| Huella del corpus, versión de etiquetas, modelo y revisión de embeddings, versión del código | Evitar comparar ejecuciones incompatibles. |

Guardar artefactos locales con perfiles ficticios; no volcar vectores completos, secretos ni URLs
con credenciales. En producción, cualquier telemetría futura será agregada y no incluirá perfiles
o consultas con datos personales.

## 3. Métricas y reporte

Evaluar inicialmente `k = 1, 3, 5, 8, 12, 16` con resultados hasta el máximo `k`. Estos cortes sirven
para experimentar: no cambian el valor de producción.

| Métrica | Definición y propósito |
| --- | --- |
| Precision@k | Positivos entre los primeros `k`, dividido por `k`. Penaliza devolver menos resultados; acompañar de precisión sobre los resultados realmente devueltos. |
| Recall@k | Positivos recuperados dividido por positivos existentes en la referencia, indicando si esta es exhaustiva o de pool. |
| Hit Rate@k | Fracción de consultas con al menos un positivo en los primeros `k`. |
| MRR@k | Media del inverso de la posición del primer positivo dentro de `k`; cero si no aparece. |
| nDCG@k | DCG con ganancia `2^relevance - 1` y descuento `log2(position + 1)`, dividido por el ranking ideal de la referencia. |
| `judged@k` | Proporción de resultados devueltos en ese corte con los juicios necesarios completos. |
| Tasa de incompatibilidad | Resultados incompatibles entre resultados cuya compatibilidad fue revisada. Mostrar también pendientes y número de consultas afectadas. |
| Cobertura útil del catálogo | Grupos necesarios con al menos una opción relevante y elegible en la unión deduplicada, dividido por grupos necesarios. |
| Opciones útiles por grupo | Número de alternativas relevantes y elegibles para cada grupo; una sola opción puede ser insuficiente. |
| Redundancia entre consultas | Apariciones repetidas antes de deduplicar y proporción de IDs únicos. |
| Recuperación vacía y latencia | Frecuencia de catálogos vacíos y latencias p50/p95. |

Para consultas sin positivos confirmados, marcar Recall y nDCG como no aplicables y evaluar aparte
si se rechazan candidatos no válidos. No eliminarlas silenciosamente del informe. Una referencia
vacía por falta de revisión no permite evaluar correctamente el rechazo.

Reportar medias macro por consulta y por perfil, distribución, peores casos y cortes por entorno,
objetivo, grupo y restricciones. No ocultar un fallo de seguridad con una buena media global.
Usar intervalos de incertidumbre mediante bootstrap por perfil, manteniendo juntas sus consultas.

Generar `report.json`, `report.csv` y un resumen Markdown con configuración, cobertura de etiquetas,
métricas, fallos y diferencias frente al baseline. Mantener el detalle por consulta para inspección.

## 4. Coseno como diagnóstico y calibración

### Diagnóstico sin filtrado

En el baseline registrar:

- Distribuciones de similitud para positivos, negativos e incompatibles.
- Similitud del primer resultado, del último admitido y del mejor positivo.
- Margen entre primer y segundo resultado, y entre el resultado `k` y `k+1` cuando estén disponibles.
- Relación entre similitud, etiquetas y grupo/entorno.

El margen solo indica separación entre candidatos, no corrección. Si positivos y negativos se
solapan mucho, un umbral global puede no ser útil. Un ejercicio incompatible con similitud alta
es evidencia de que el coseno no sustituye a las restricciones.

### Calibración de un posible umbral

Definir una política candidata: aceptar hasta `k` resultados con `similarity >= threshold`.
Su equivalente es `distance <= 1 - threshold`. Mantener como comparación obligatoria la política
actual sin umbral.

1. Barrer umbrales sobre el conjunto de calibración y simular exactamente la política propuesta.
2. Para cada umbral medir precisión, recall, Hit Rate, cobertura útil, incompatibilidades,
   resultados admitidos y consultas vacías.
3. Construir la curva precisión-recall con candidatos etiquetados, dejando claro si representa
   solo el pool recuperado y no todo el corpus.
4. Seleccionar el umbral con una regla acordada antes de consultar prueba: por ejemplo, maximizar
   precisión sujeto a mínimos de recall y cobertura definidos tras estudiar el baseline.
5. Medir la política seleccionada una sola vez en prueba y publicar comparación e incertidumbre.
6. Si no hay una mejora consistente o faltan etiquetas, conservar el comportamiento sin umbral.

No utilizar accuracy como métrica principal: puede resultar engañosa con muchos negativos.
No ajustar umbrales por grupo o entorno con pocas muestras; empezar por uno global y justificar
cualquier segmentación posterior con evidencia suficiente.

Un umbral puede dejar un grupo sin opciones. Si se prueba recuperar a mayor profundidad para
compensar filtros adicionales, declararlo como otra variante y medir su latencia; no asumir que
añadir más resultados supera un umbral de similitud. Nunca rellenar automáticamente con resultados
rechazados para aparentar cobertura.

Cuando no haya opciones suficientes, comprobar explícitamente el manejo existente de catálogo vacío
y de catálogo parcial antes de desplegar. No eliminar silenciosamente restricciones obligatorias.
El umbral deberá recalibrarse al cambiar embeddings, corpus, filtros o construcción de consultas.

## 5. Experimentos controlados

Después de congelar el baseline, cambiar una variable cada vez:

| Variante | Hipótesis |
| --- | --- |
| Distintos `top_k` | Más alternativas pueden mejorar cobertura a costa de ruido, tokens y latencia. |
| Equipamiento realmente disponible | Puede reducir incompatibilidades frente a las listas generales por entorno. |
| Grupo muscular como filtro estructurado | Puede mejorar precisión por grupo; comprobar que no excluye alternativas válidas. |
| Consultas con campos alineados con el corpus | Puede mejorar ranking frente a usar objetivos y entorno en campos con otro significado. |
| Umbral de coseno | Puede retirar negativos, pero también reducir recall y dejar grupos vacíos. |

Evaluar las variantes con las mismas etiquetas, corpus y particiones. Mantener fijo el resto de la
configuración. No introducir reranking, nuevos modelos o dependencias antes de saber qué falla.

Para las variantes prometedoras, ejecutar también los casos del entrenador con sus nuevos
catálogos. Comparar cobertura, errores del plan, reparaciones, tokens y latencia. Conservar los
catálogos antiguos: no sobrescribir el baseline al regenerarlos.

## 6. Entregables y secuencia de implementación

| Fase | Entregable | Criterio de cierre |
| --- | --- | --- |
| 1. Referencia | `evals/retrieval/README.md`, perfiles ficticios, rúbrica, etiquetas y particiones. | Etiquetas revisadas, alcance de la referencia declarado y casos sin positivos identificados. |
| 2. Trazas | Coincidencias tipadas y búsqueda trazada compartida con el flujo actual. | Mismos ejercicios y mismo orden que antes; distancias disponibles por consulta. |
| 3. Runner | `devtools/retrieval_eval.py` y reportes locales en `runs/retrieval-evaluations/`. | Ejecución sin LLM, métricas reproducibles y errores explícitos ante artefactos inválidos. |
| 4. Baseline | Informe de recuperación actual con fallos por caso y diagnóstico de coseno. | Todos los resultados comparados están juzgados o el informe declara su incompletitud. |
| 5. Experimentos | Comparativa de variantes y calibración en partición reservada. | Decisión documentada, incluida la posibilidad de no usar umbral. |
| 6. Adopción opcional | Configuración y documentación del cambio seleccionado, si se justifica. | Sin regresiones de restricciones obligatorias, mejora en prueba y comportamiento vacío/parcial verificado. |

Los nombres de módulos y comandos nuevos son propuestas, no interfaces existentes. Añadir una
entrada de Makefile siguiendo las herramientas `trainer-debug` y `trainer-compare`; documentar
el comando efectivo al implementar. No modificar dependencias para calcular fórmulas que puedan
resolverse con la biblioteca estándar.

Si se adopta un umbral, añadir una configuración validada en `IASettings`, desactivada por defecto,
y documentarla en `.env.example`. Desplegar primero en modo diagnóstico, sin descartar ejercicios.
Permitir volver al baseline desactivando la configuración, sin migraciones destructivas.

## Pruebas y validación previstas

- Unitarias de métricas con rankings conocidos, resultados cortos, empates, duplicados, juicios
  pendientes, consultas sin positivos y distintos grados de relevancia.
- Orden determinista en empates mediante un criterio secundario estable documentado; comprobar
  cualquier diferencia respecto al baseline antes de adoptarlo.
- Unitarias del repositorio para seleccionar distancia, convertir similitud y aplicar el límite
  de umbral en su frontera exacta.
- Integración contra pgVector con vectores conocidos: misma dirección, ortogonales y dirección
  opuesta; comprobar distancias, ranking, filtro de equipo y política de umbral.
- Regresión del recuperador: siete consultas, orden y deduplicación preservados sin umbral.
- Runner: validación de IDs, metadatos, particiones, valores no finitos, versiones incompatibles
  y ausencia de etiquetas; no producir un informe de éxito ante fallos de servicios.
- Reproducibilidad de la evaluación sobre resultados congelados, sin base de datos ni LLM.
- Integración del entrenador con catálogo vacío/parcial y opciones incompatibles identificadas.

Durante la implementación, ejecutar pruebas focalizadas y los controles Ruff y mypy del proyecto.
Antes de cerrar cambios de código, ejecutar la suite completa:

```bash
uv run pytest tests --cov=src/fitcoach --cov-fail-under=80
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

Separar CI determinista, con artefactos congelados y vectores de prueba, de la evaluación real
contra embedder y corpus versionado. El estado del servicio externo no debe convertir la CI en
una comparación de calidad irreproducible.

## Criterio de éxito

Disponer de una respuesta reproducible a estas preguntas:

1. Qué ejercicios relevantes recuperamos, cuáles omitimos y dónde aparecen en el ranking.
2. Qué restricciones incumplen los candidatos y qué grupos quedan sin alternativas útiles.
3. Si el coseno separa positivos de negativos y qué se pierde al aplicar un umbral.
4. Si una variante mejora casos nuevos sin ocultar regresiones bajo la media.
5. Si el fallo procede del corpus, de la recuperación o de la generación del plan.

Los objetivos numéricos de precisión, recall y cobertura se acordarán tras obtener el baseline.
La decisión de usar un umbral es un resultado de la evaluación, no un requisito para dar el plan
por completado.
