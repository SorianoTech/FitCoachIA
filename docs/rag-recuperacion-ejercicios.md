# Recuperación RAG de ejercicios con pgVector

FitCoachIA utiliza una base de datos vectorial para reducir el catálogo completo a un conjunto
pequeño de ejercicios relacionados con cada grupo muscular y compatibles con el material declarado
por el usuario.

La recuperación no confía únicamente en la similitud semántica. Es una búsqueda híbrida:

```text
filtros SQL estrictos
+ ordenación por similitud vectorial
+ validación posterior del plan
```

Los filtros determinan qué ejercicios son admisibles. La distancia vectorial decide cuáles aparecen
primero entre esos candidatos. El resultado se transforma después en un bloque de datos que recibe
el entrenador.

## Ventajas de la base de datos vectorial

Una consulta SQL convencional puede filtrar por campos conocidos:

```sql
WHERE target = 'pectorals'
  AND equipment IN ('barbell', 'body weight', 'dumbbell')
```

Pero esos filtros no indican qué ejercicios son más representativos. Sin otra ordenación,
PostgreSQL podría devolver candidatos por identificador o por orden físico, incluyendo variantes
poco útiles antes que movimientos claros.

Los embeddings permiten ordenar por el significado combinado de:

- Nombre del ejercicio.
- Categoría y parte corporal.
- Material.
- Grupo muscular almacenado en el corpus.
- Target anatómico principal.
- Músculos secundarios.

Así, una consulta relacionada con pecho puede priorizar ejercicios como `barbell bench press`,
`dumbbell bench press`, `incline chest press`, `chest fly` o `push-up`, aunque sus nombres no
contengan exactamente las mismas palabras.

La búsqueda vectorial aporta principalmente:

1. Ranking semántico entre candidatos compatibles.
2. Recuperación de variantes relacionadas sin enumerar todos sus nombres.
3. Un `top_k` reducido que evita enviar todo el catálogo al LLM.
4. Una interfaz común para generaciones, renovaciones y sustituciones.
5. Escalabilidad del ranking cuando aumenta el número de ejercicios.

No convierte la similitud en una garantía de seguridad. Las restricciones obligatorias siguen
aplicándose mediante filtros y validaciones deterministas.

## Preparación del catálogo

Antes de poder buscar, cada ejercicio se transforma en un texto de metadatos. Por ejemplo, el
catálogo de evaluación contiene este ejercicio real:

```json
{
  "id": 289,
  "name": "dumbbell bench press",
  "category": "chest",
  "body_part": "chest",
  "equipment": "dumbbell",
  "muscle_group": "triceps",
  "target": "pectorals",
  "secondary_muscles": [
    "triceps",
    "shoulders"
  ]
}
```

El loader lo convierte en:

```text
name: dumbbell bench press
| category: chest
| body_part: chest
| equipment: dumbbell
| muscle_group: triceps
| target: pectorals
| secondary_muscles: triceps, shoulders
```

El servicio de embeddings transforma ese texto en un vector de 384 números:

```text
[0.018, -0.073, 0.121, ..., -0.032]
```

Los números anteriores son ilustrativos. El vector real depende del modelo de embeddings. El
resultado completo se guarda en la columna:

```text
exercises.metadata_vector
```

Todos los ejercicios deben vectorizarse con el mismo modelo y dimensiones que las consultas. Una
diferencia de dimensiones hace que la aplicación rechace la búsqueda, porque las distancias
dejarían de tener significado.

## Formación de las consultas

Para generar o renovar un plan no se crea una única consulta de cuerpo completo. Se construye una
consulta independiente para cada grupo:

| Grupo | Targets admitidos |
|---|---|
| `chest` | `pectorals` |
| `back` | `lats`, `upper back`, `traps`, `spine` |
| `legs` | `quads`, `hamstrings`, `glutes`, `calves`, `adductors`, `abductors` |
| `shoulders` | `delts` |
| `arms` | `biceps`, `triceps`, `forearms` |
| `core` | `abs`, `serratus anterior` |
| `cardio` | `cardiovascular system` |

Separar los grupos evita que una consulta genérica quede dominada por los ejercicios más comunes y
no aporte opciones para otras partes del cuerpo.

### Normalización del material

El material declarado en el perfil se normaliza al vocabulario del catálogo:

| Declaración | Valor canónico |
|---|---|
| `mancuernas`, `mancuerna` | `dumbbell` |
| `bandas`, `banda elástica`, `band` | `resistance band` |
| `barra` | `barbell` |
| `peso corporal` | `body weight` |
| `polea`, `poleas` | `cable` |
| `maquina smith` | `smith machine` |

`body weight` se añade siempre. Si un valor no pertenece al vocabulario conocido, la aplicación
solicita una aclaración en lugar de ampliar el filtro silenciosamente.

El corpus puede conservar tanto `band` como `resistance band`; por eso el filtro SQL expande ese
alias. Aparatos realmente distintos, como barra convencional, barra EZ y barra olímpica, no se
consideran equivalentes.

## Ejemplo completo

Supongamos un perfil con:

```json
{
  "training": {
    "equipment": [
      "barbell",
      "dumbbell"
    ]
  }
}
```

El material efectivo queda:

```text
barbell, body weight, dumbbell
```

### Textos enviados al embedder

La aplicación construye siete textos:

```text
muscle_group: chest | target: pectorals | equipment: barbell, body weight, dumbbell

muscle_group: back | target: lats, spine, traps, upper back
| equipment: barbell, body weight, dumbbell

muscle_group: legs | target: abductors, adductors, calves, glutes, hamstrings, quads
| equipment: barbell, body weight, dumbbell

muscle_group: shoulders | target: delts | equipment: barbell, body weight, dumbbell

muscle_group: arms | target: biceps, forearms, triceps
| equipment: barbell, body weight, dumbbell

muscle_group: core | target: abs, serratus anterior
| equipment: barbell, body weight, dumbbell

muscle_group: cardio | target: cardiovascular system
| equipment: barbell, body weight, dumbbell
```

Los textos se envían juntos:

```http
POST /embed
Content-Type: application/json
```

```json
{
  "texts": [
    "muscle_group: chest | target: pectorals | equipment: barbell, body weight, dumbbell",
    "muscle_group: back | target: lats, spine, traps, upper back | equipment: barbell, body weight, dumbbell",
    "muscle_group: legs | target: abductors, adductors, calves, glutes, hamstrings, quads | equipment: barbell, body weight, dumbbell",
    "muscle_group: shoulders | target: delts | equipment: barbell, body weight, dumbbell",
    "muscle_group: arms | target: biceps, forearms, triceps | equipment: barbell, body weight, dumbbell",
    "muscle_group: core | target: abs, serratus anterior | equipment: barbell, body weight, dumbbell",
    "muscle_group: cardio | target: cardiovascular system | equipment: barbell, body weight, dumbbell"
  ]
}
```

El embedder devuelve siete vectores de 384 dimensiones, uno por texto.

## Consulta a pgVector

Para pecho, SQLAlchemy construye conceptualmente esta consulta:

```sql
SELECT
    exercises.*,
    exercises.metadata_vector <=> :chest_vector AS distance
FROM exercises
WHERE exercises.metadata_vector IS NOT NULL
  AND exercises.target IN ('pectorals')
  AND exercises.equipment IN (
      'barbell',
      'body weight',
      'dumbbell'
  )
ORDER BY
    exercises.metadata_vector <=> :chest_vector ASC,
    exercises.id ASC
LIMIT 8;
```

`<=>` es el operador de distancia coseno de pgVector. El desempate por ID hace estable el orden
cuando dos ejercicios tienen la misma distancia.

La búsqueda se divide en dos partes.

### Filtros obligatorios

```sql
target IN ('pectorals')
equipment IN ('barbell', 'body weight', 'dumbbell')
```

Estos filtros descartan antes del ranking:

- Ejercicios cuyo target principal pertenece a otro grupo.
- Ejercicios que requieren material no confirmado.
- Registros sin vector.

### Orden vectorial

```sql
ORDER BY metadata_vector <=> :chest_vector
```

La relación entre distancia y similitud es:

```text
cosine_similarity = 1 - cosine_distance
```

Una distancia menor representa mayor similitud semántica. No representa una probabilidad de
corrección ni una valoración clínica.

## Ejemplo de ranking recuperado

Usando ejercicios reales del catálogo, un resultado ilustrativo podría ser:

| Posición | ID | Ejercicio | Target | Material | Distancia |
|---:|---:|---|---|---|---:|
| 1 | 25 | `barbell bench press` | `pectorals` | `barbell` | 0.18 |
| 2 | 289 | `dumbbell bench press` | `pectorals` | `dumbbell` | 0.21 |
| 3 | 1289 | `dumbbell one arm incline chest press` | `pectorals` | `dumbbell` | 0.27 |
| 4 | 40 | `barbell front raise and pullover` | `pectorals` | `barbell` | 0.39 |

Los ejercicios e IDs proceden del catálogo de evaluación. Las distancias son exclusivamente un
ejemplo para explicar el ranking; no corresponden a una ejecución registrada.

Todos los resultados cumplen los filtros. El vector determina su posición relativa.

Un registro como:

```json
{
  "id": 3286,
  "name": "weighted muscle up",
  "equipment": "weighted",
  "target": "lats"
}
```

no puede entrar en la búsqueda de pecho del ejemplo, aunque sus instrucciones mencionen el pecho:

```text
target != pectorals
equipment no confirmado
```

La similitud vectorial nunca puede saltarse esos filtros.

## Unión y deduplicación

Cada grupo recupera hasta `rag_top_k` ejercicios; el valor predeterminado es `8`. Los resultados de
los siete rankings se concatenan preservando el orden y se deduplican por ID.

No existe un ranking vectorial global del catálogo final. Cada posición tiene sentido dentro de la
consulta de su grupo. La unión proporciona variedad anatómica para que el entrenador pueda
construir el plan.

## Contexto enviado al entrenador

Los vectores y distancias no se envían al LLM. Los ejercicios recuperados se convierten en texto:

```text
AVAILABLE EXERCISES (reference data, use only these ids):

- id: 25
  | name: barbell bench press
  | body_part: chest
  | equipment: barbell
  | muscle_group: chest
  | target: pectorals
  | secondary_muscles: triceps, shoulders
  | instructions: Lie flat on a bench...

- id: 289
  | name: dumbbell bench press
  | body_part: chest
  | equipment: dumbbell
  | muscle_group: chest
  | target: pectorals
  | secondary_muscles: triceps, shoulders
  | instructions: Lie flat on a bench...

- id: 1289
  | name: dumbbell one arm incline chest press
  | body_part: chest
  | equipment: dumbbell
  | muscle_group: chest
  | target: pectorals
  | secondary_muscles: shoulders, triceps
  | instructions: Adjust the incline bench...
```

Este bloque sustituye `{{rag_context}}` en el prompt del entrenador. Las instrucciones se limpian
de caracteres de control y se limitan a 400 caracteres por ejercicio.

Al mismo tiempo, la aplicación conserva los IDs permitidos:

```python
{25, 40, 289, 1289}
```

Si el modelo devuelve un ejercicio inexistente en ese conjunto:

```json
{
  "exercise_id": 999999
}
```

la respuesta se rechaza y entra en el mecanismo de reparación. El esquema JSON puede ser válido y
aun así fallar por utilizar un ID inventado.

## Sustitución de un ejercicio

Las sustituciones utilizan una consulta más específica. Para cambiar un press de banca por una
molestia declarada podría formarse:

```text
name: barbell bench press
| muscle_group: chest
| target: pectorals
| equipment: body weight, dumbbell
| variation: molestia en el hombro
```

La razón participa en el embedding, pero SQL mantiene restricciones obligatorias:

```sql
SELECT
    exercises.*,
    exercises.metadata_vector <=> :variation_vector AS distance
FROM exercises
WHERE exercises.metadata_vector IS NOT NULL
  AND exercises.target = 'pectorals'
  AND exercises.equipment IN ('body weight', 'dumbbell')
  AND exercises.id NOT IN (:original_exercise_id)
ORDER BY
    exercises.metadata_vector <=> :variation_vector ASC,
    exercises.id ASC
LIMIT 8;
```

Después de recuperar, la aplicación vuelve a comprobar que:

- El candidato no sea el ejercicio original.
- Mantenga exactamente el mismo `target`.
- Utilice material disponible.

Una razón textual no autoriza relajar estas restricciones.

## Capas de fiabilidad

La corrección del sistema no depende de una única puntuación:

1. **Vocabulario canónico:** los grupos se derivan de targets anatómicos conocidos.
2. **Material normalizado:** aliases conocidos se traducen y valores desconocidos se rechazan.
3. **Filtros SQL:** target y equipamiento limitan el conjunto admisible.
4. **Ranking vectorial:** prioriza candidatos dentro de ese conjunto.
5. **Top-k por grupo:** evita que los grupos más comunes monopolicen el catálogo.
6. **Deduplicación:** un ejercicio no se repite en el contexto final.
7. **Lista de IDs permitidos:** el modelo no puede usar ejercicios no recuperados.
8. **Evaluación del plan:** se comprueban restricciones del perfil, material, cobertura y
   duplicados.

La base vectorial no identifica por sí sola el ejercicio perfecto ni clínicamente seguro. Su
responsabilidad es recuperar y ordenar un catálogo acotado y semánticamente relacionado. Las reglas
deterministas protegen las condiciones que no deben depender de similitud.

## Limitaciones actuales

Las consultas generales incorporan directamente:

- Grupo muscular.
- Targets anatómicos.
- Material confirmado.

No incluyen directamente en el texto de búsqueda:

- Objetivo deportivo.
- Nivel de experiencia.
- Duración disponible.
- Lesiones o restricciones completas del perfil.

Esos datos se proporcionan al entrenador y se validan en el plan, pero no participan actualmente
en el ranking general del catálogo. En sustituciones, la razón sí se añade al texto semántico.

Tampoco se aplica un umbral mínimo de similitud. Se recuperan hasta `top_k` candidatos que cumplan
los filtros, ordenados por distancia. Las distancias se registran para diagnóstico, pero todavía no
existe una evaluación etiquetada que permita interpretarlas como calidad.

## Flujo resumido

```mermaid
flowchart LR
    Profile[Perfil y material] --> Queries[7 consultas por grupo]
    Queries --> Embedder[Embedder: vectores de 384 dimensiones]
    Embedder --> PgVector[(pgVector)]
    PgVector --> Filters[Filtros de target y material]
    Filters --> Ranking[Ranking por distancia coseno]
    Ranking --> TopK[Top-k por grupo]
    TopK --> Dedup[Unión y deduplicación]
    Dedup --> Context[Contexto RAG legible]
    Context --> Trainer[Agente entrenador]
    Trainer --> Validation[Validación de IDs y plan]
```

## Código relacionado

- `infra/vector-db/loader/loader.py`: texto y embeddings iniciales del catálogo.
- `src/fitcoach/domain/exercise_catalogue.py`: grupos, targets y normalización de material.
- `src/fitcoach/service/agent/rag_context.py`: consultas y contexto que recibe el entrenador.
- `src/fitcoach/service/agent/exercise_retriever.py`: recuperación por grupo y deduplicación.
- `src/fitcoach/infrastructure/ia/embedder_client.py`: comunicación con el servicio de embeddings.
- `src/fitcoach/infrastructure/vectordb/pgvector_exercise_repository.py`: filtros y ranking coseno.
- `src/fitcoach/service/agent/trainer_chain.py`: inserción del catálogo y validación de IDs.
- [`vector-db.md`](vector-db.md): infraestructura y operación de la base vectorial.
- [`plan/rag-retrieval-quality.md`](plan/rag-retrieval-quality.md): plan de evaluación de calidad.
