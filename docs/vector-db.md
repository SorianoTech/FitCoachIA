# Base de datos vectorial y servicio de embeddings

El catálogo de ejercicios vive en una instancia de PostgreSQL con la extensión
[pgvector](https://github.com/pgvector/pgvector), separada de la base de datos de la aplicación.
El agente [`trainer`](trainer-agent.md) la consulta para construir sus planes.

La aplicación **solo lee** de esta base de datos. No hay migraciones de Alembic que la toquen: su
esquema y sus datos los define `infra/vector-db/ddl/`.

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

### Texto de consulta

El cargador vectorizó, por cada ejercicio, un texto con esta forma:

```text
name: ... | category: ... | body_part: ... | equipment: ... | muscle_group: ... | target: ... | secondary_muscles: ...
```

`build_query_text()` en `src/fitcoach/service/agent/rag_context.py` reproduce ese formato. Si se
modifica uno, hay que modificar el otro.

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

pgAdmin queda disponible en el puerto que indique `PGADMIN_PORT` (8010 por defecto).

## Acceso de solo lectura

La aplicación se conecta con `fitcoach_ro`, no con el rol `fitcoach` del volcado (que es
`SUPERUSER`). La contraseña sale de `VECTOR_DB_RO_PASSWORD` al inicializar el contenedor:

```dotenv
vector_db_url=postgresql+asyncpg://fitcoach_ro:<secreto>@pgvector:5432/fitcoach
```

> **Rotación pendiente:** el volcado inicial incluye el hash SCRAM del rol `fitcoach` en el
> repositorio. No es texto plano, pero es atacable offline. Conviene rotar esa contraseña en los
> entornos reales y no reutilizarla en ningún otro sitio.

## Red

`infra/vector-db/docker-compose.vector-db.yml` es un proyecto Compose independiente
(`name: fitcoach-vector-db`), con su propio ciclo de vida: los ejercicios se cargan una vez y
sobreviven a los despliegues de la aplicación.

El servicio `pgvector` está en dos redes: `fit-coach-net`, para pgAdmin, y `proxy-network`, que es
por donde lo alcanza la aplicación.

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
