# Base de datos vectorial y servicio de embeddings

El catálogo de ejercicios vive en una instancia de PostgreSQL con la extensión
[pgvector](https://github.com/pgvector/pgvector), separada de la base de datos de la aplicación.
El agente [`trainer`](trainer-agent.md) la consulta para construir sus planes. La recuperación
normal utiliza un rol de solo lectura; la publicación de ejercicios aprobados utiliza otro rol con
permisos de inserción limitados.

No hay migraciones de Alembic que administren esta base de datos: su esquema, datos y roles los
define `infra/vector-db/ddl/`.

## Esquema

```sql
CREATE TABLE public.exercises (
    id bigint NOT NULL,
    name text NOT NULL,
    category text,
    body_part text,
    equipment text,
    muscle_group text,
    target text,
    secondary_muscles text[],
    instructions_en text,
    instructions_tr text,
    created_at timestamp with time zone,
    metadata_vector public.vector(384)
);

CREATE TABLE public.exercise_media (
    id integer NOT NULL,
    exercise_id bigint NOT NULL,
    image_path text,
    gif_path text,
    image_data bytea,
    gif_data bytea
);
```

El índice que hace viable la búsqueda:

```sql
CREATE INDEX exercises_metadata_vec_idx ON public.exercises
    USING hnsw (metadata_vector public.vector_cosine_ops) WITH (m='16', ef_construction='64');
```

`exercise_media` guarda imágenes y GIF de cada ejercicio. Hoy la aplicación no los usa; están ahí
para cuando el plan se entregue con material visual.

## El modelo de embeddings no se puede cambiar a la ligera

`metadata_vector` son 384 dimensiones generadas con **`sentence-transformers/all-MiniLM-L6-v2`**
(ver `infra/vector-db/loader/loader.py`). Dos consecuencias:

1. **La consulta debe usar el mismo modelo.** Un vector producido por otro modelo vive en otro
   espacio: la distancia coseno contra el corpus deja de significar nada, y la búsqueda devuelve
   resultados plausibles pero arbitrarios. Por eso existe el servicio `embedder`.
2. **Cambiar de modelo obliga a re-vectorizar todo.** Habría que volver a ejecutar el cargador sobre
   el conjunto de ejercicios, regenerar el volcado SQL y reconstruir la imagen de pgVector.

Como red de seguridad, el `embedder` no arranca si su modelo no produce 384 dimensiones, y
`EmbedderClient` rechaza cualquier vector cuya dimensión no coincida.

### Altas incrementales

Añadir un ejercicio aprobado no reconstruye el corpus completo:

1. La aplicación compone sus metadatos semánticos con el mismo formato que usó el cargador.
2. El `embedder` genera únicamente el vector de ese ejercicio.
3. El rol `fitcoach_writer` inserta la fila en `exercises` junto a su `metadata_vector`.
4. El índice HNSW incorpora la nueva fila automáticamente y las siguientes consultas RAG pueden
   recuperarla sin reiniciar pgVector ni regenerar el volcado inicial.

La aprobación vuelve a generar el vector definitivo aunque la detección de duplicados haya usado
antes un embedding temporal. De este modo, la publicación no depende de datos transitorios ni de
que la aplicación haya permanecido activa desde la creación del borrador.

Solo hay que re-vectorizar todo el catálogo si cambia el modelo, la dimensionalidad o el formato de
metadatos del corpus. Modificar en el futuro los campos vectorizados de un ejercicio publicado
exigiría regenerar el embedding de esa fila.

### Texto de consulta

El cargador vectorizó, por cada ejercicio, un texto con esta forma:

```text
name: ... | category: ... | body_part: ... | equipment: ... | muscle_group: ... | target: ... | secondary_muscles: ...
```

`build_query_text()` conserva el formato de metadatos, pero usa targets anatómicos
(`pectorals`, `lats`, etc.) y equipamiento confirmado. No coloca objetivos deportivos en
`target` ni entornos como `gym` en `category`, porque no tienen el mismo significado.
Cambiar el texto del corpus exige re-vectorizarlo; cambiar la consulta no.

### Clasificación y disponibilidad

El campo original `muscle_group` del volcado no es una clasificación fiable del músculo
principal. La aplicación deriva el grupo canónico a partir de `target`, usando el mapa
compartido en `domain/exercise_catalogue.py`. No modifica registros ni embeddings.
Targets no clasificados conservan sus metadatos, pero no entran en la recuperación por
grupo; una fuente nueva debe revisar su vocabulario antes de incorporarse.

La búsqueda general filtra por los targets del grupo y por el material declarado,
añadiendo peso corporal. La misma disponibilidad se aplica en gimnasio, casa, exterior
y entorno mixto, tanto al primer plan como a renovaciones y sustituciones. No se
presupone que un gimnasio tenga cualquier aparato. Material desconocido requiere
aclaración; no se amplía el filtro automáticamente.

`band` y `resistance band` se consideran equivalentes. Las búsquedas admiten ambos valores
del corpus y la representación de dominio devuelve `resistance band`. Aparatos distintos,
como barra EZ, barra olímpica y barra convencional, no se convierten automáticamente
en equivalentes. Las sustituciones conservan el mismo `target`, sin exigir el
`muscle_group` original potencialmente incorrecto.

### Trazas de recuperación

`search_scored()` devuelve `ExerciseMatch` con distancia coseno y similitud
(`1 - distancia`). `search()` conserva la respuesta de ejercicios sin puntuación.
El orden es distancia ascendente e ID como desempate. Vectores de consulta nulos,
no finitos o con dimensión incorrecta se rechazan explícitamente.

`ExerciseRetriever.retrieve_traced()` expone por grupo los filtros y las coincidencias
en orden, además de la unión deduplicada. La traza es local a la petición; no se guarda
en los planes ni contiene perfiles, consultas libres o vectores.
En INFO se registra `RAG ranking` con grupo, cantidad y distancias mínima/máxima.
Grupos vacíos generan un WARNING. No se registran perfiles ni razones de sustitución.

Estos datos son diagnósticos, no probabilidades de relevancia ni garantías clínicas.
No se aplica un umbral de similitud. La evaluación etiquetada de
[calidad de recuperación](plan/rag-retrieval-quality.md) sigue pendiente.
Los filtros SQL limitan los resultados admisibles; el orden físico de ejecución y
la cobertura de una búsqueda HNSW filtrada dependen del planificador y deben medirse.

## Servicio `embedder`

`infra/embedder/` es un FastAPI mínimo que expone el modelo:

| Ruta | Qué hace |
| --- | --- |
| `POST /embed` | `{"texts": ["..."]}` → `{"model": ..., "dimensions": 384, "vectors": [[...]]}` |
| `GET /health` | 200 solo cuando el modelo está cargado en memoria |

Vive en su propio contenedor a propósito: `sentence-transformers` arrastra torch (2-3 GB) y no tiene
nada que hacer dentro de la imagen del webhook, que se mantiene en ~200 MB.

El modelo se descarga **durante el build**, no en el arranque, así que el contenedor no depende de
HuggingFace ni de la red para estar sano. La contrapartida es que la imagen es grande y que cambiar
`EMBEDDER_MODEL` obliga a reconstruirla.

`GET /health` responde 503 mientras el modelo se carga; el `healthcheck` del compose usa esa sonda,
de modo que la aplicación no arranca antes de que el embedder pueda responder.

## Levantar el entorno

```bash
make vector-up      # pgVector + pgAdmin
make vector-logs
make vector-down    # conserva el volumen con la carga inicial
```

`make vector-down` **no** borra el volumen a propósito: la carga inicial son 283 MB repartidos en 8
ficheros y volver a aplicarla tarda varios minutos. Para borrarla de verdad hay que hacerlo
explícitamente.

La primera vez, el contenedor aplica en orden alfabético todo lo que hay en
`infra/vector-db/ddl/`:

| Fichero | Contenido |
| --- | --- |
| `001_2026-09-18_Initial-exercises-load_part-01..08.sql` | Volcado inicial, troceado para respetar el límite de 100 MB por fichero de GitHub. |
| `002_2026-09-21_readonly-role.sql` | Rol `fitcoach_ro`, de solo lectura, que usa la aplicación. |
| `003_2026-10-04_exercise-writer.sql` | Tabla idempotente de publicaciones, ajuste de secuencia y rol restringido `fitcoach_writer`. |

pgAdmin queda disponible en el puerto que indique `PGADMIN_PORT` (8010 por defecto).

## Roles de acceso

La recuperación se conecta con `fitcoach_ro`, no con el rol `fitcoach` del volcado (que es
`SUPERUSER`). La contraseña sale de `VECTOR_DB_RO_PASSWORD` al inicializar el contenedor:

```dotenv
vector_database_url=postgresql+asyncpg://fitcoach_ro:<secreto>@pgvector:5432/fitcoach
```

La publicación moderada usa `fitcoach_writer`, cuya contraseña se configura mediante
`VECTOR_DB_WRITER_PASSWORD` y se referencia desde la aplicación:

```dotenv
vector_database_writer_url=postgresql+asyncpg://fitcoach_writer:<secreto>@pgvector:5432/fitcoach
```

Este rol puede insertar únicamente las columnas necesarias de `exercises`, utilizar su secuencia y
leer o insertar en `exercise_publications`. No puede actualizar ni borrar libremente el catálogo.

> **Rotación pendiente:** el volcado inicial incluye el hash SCRAM del rol `fitcoach` en el
> repositorio. No es texto plano, pero es atacable offline. Conviene rotar esa contraseña en los
> entornos reales y no reutilizarla en ningún otro sitio.

## Red

`infra/vector-db/docker-compose.vector-db.yml` es un proyecto Compose independiente
(`name: fitcoach-vector-db`), con su propio ciclo de vida: los ejercicios se cargan una vez y
sobreviven a los despliegues de la aplicación.

El Compose local conecta `pgvector` y pgAdmin a `fit-coach-net`. En el servidor se usan los
overrides por entorno:

- `docker-compose.vector-db.dev.yml` conecta pgVector a `fitcoach-dev-internal` y publica pgAdmin
  mediante `proxy-network`.
- `docker-compose.vector-db.prod.yml` conecta pgVector y pgAdmin exclusivamente a
  `fitcoach-prod-internal`.

De este modo la aplicación alcanza pgVector por su red backend y la base vectorial nunca necesita
pertenecer a `proxy-network`.

## Consultas útiles

```sql
-- Tamaño del catálogo
SELECT count(*) FROM exercises;

-- Qué equipamiento existe (los valores que usa el prefiltro)
SELECT equipment, count(*) FROM exercises GROUP BY equipment ORDER BY 2 DESC;

-- Grupos musculares disponibles
SELECT muscle_group, count(*) FROM exercises GROUP BY muscle_group ORDER BY 2 DESC;

-- Vecinos más cercanos a un ejercicio concreto (comprobar que el índice funciona)
SELECT e2.id, e2.name, e1.metadata_vector <=> e2.metadata_vector AS distance
FROM exercises e1, exercises e2
WHERE e1.id = 1 AND e2.id <> e1.id
ORDER BY distance
LIMIT 10;
```

## En los tests

Los tests de integración **no** usan el volcado real: 283 MB y varios minutos de arranque no caben
en CI. `tests/docker-compose-test.yml` levanta la imagen oficial de pgVector con
`tests/fixtures/exercises_min.sql`, que reproduce el mismo DDL con 10 ejercicios y vectores
deterministas, y un stub de embeddings que devuelve un vector constante.

Así la recuperación es reproducible y la comprobación que importa —que todos los `exercise_id` del
plan existen de verdad en `exercises`— se ejecuta contra pgVector real.

El volcado completo solo se ejercita a mano con `make vector-up`.
