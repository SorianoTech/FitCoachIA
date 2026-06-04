-- Habilitar extensión pgVector
CREATE EXTENSION IF NOT EXISTS vector;

-- Tabla principal de ejercicios
CREATE TABLE IF NOT EXISTS exercises (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    category        TEXT,
    body_part       TEXT,
    equipment       TEXT,
    muscle_group    TEXT,
    target          TEXT,
    secondary_muscles TEXT[],          -- array de strings
    instructions_en TEXT,
    instructions_tr TEXT,
    created_at      TIMESTAMPTZ,
    -- Vector de metadatos (dimensión 384 para all-MiniLM-L6-v2)
    metadata_vector vector(384)
);

-- Tabla de medios binarios (imagen + gif)
CREATE TABLE IF NOT EXISTS exercise_media (
    id          SERIAL PRIMARY KEY,
    exercise_id BIGINT NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    image_path  TEXT,                 -- ruta original
    gif_path    TEXT,                 -- ruta original
    image_data  BYTEA,               -- contenido binario de la imagen
    gif_data    BYTEA                -- contenido binario del gif
);

-- Índice HNSW para búsqueda vectorial eficiente (cosine similarity)
CREATE INDEX IF NOT EXISTS exercises_metadata_vec_idx
    ON exercises
    USING hnsw (metadata_vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Índice FK para joins rápidos
CREATE INDEX IF NOT EXISTS exercise_media_exercise_id_idx
    ON exercise_media (exercise_id);
