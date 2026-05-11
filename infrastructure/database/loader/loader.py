"""
loader.py — Carga ejercicios (JSON + imágenes + GIFs) en PostgreSQL con pgVector.

Dependencias:
    pip install psycopg2-binary sentence-transformers tqdm

Uso:
    python loader.py --json exercises.json --media-dir ./ --db-url postgresql://rag_user:rag_pass@localhost:5432/exercises_db
"""

import argparse
import json
import logging
import urllib.request
from pathlib import Path

import psycopg2
import psycopg2.extras
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Construcción del texto a vectorizar
# ──────────────────────────────────────────────

def build_metadata_text(exercise: dict) -> str:
    """
    Concatena los campos de metadatos estructurados en un texto
    que será convertido en embedding.
    Ajusta aquí qué campos incluir según tu criterio semántico.
    """
    secondary = ", ".join(exercise.get("secondary_muscles") or [])
    parts = [
        f"name: {exercise.get('name', '')}",
        f"category: {exercise.get('category', '')}",
        f"body_part: {exercise.get('body_part', '')}",
        f"equipment: {exercise.get('equipment', '')}",
        f"muscle_group: {exercise.get('muscle_group', '')}",
        f"target: {exercise.get('target', '')}",
        f"secondary_muscles: {secondary}",
    ]
    return " | ".join(p for p in parts if not p.endswith(": "))


# ──────────────────────────────────────────────
# Carga de un ejercicio individual
# ──────────────────────────────────────────────

def load_exercise(cur, exercise: dict, media_dir: Path, embedding: list[float]) -> None:
    """Inserta o actualiza un ejercicio y su media en la base de datos."""

    instructions = exercise.get("instructions") or {}

    # Upsert en tabla exercises
    cur.execute(
        """
        INSERT INTO exercises (
            id, name, category, body_part, equipment,
            muscle_group, target, secondary_muscles,
            instructions_en, instructions_tr,
            created_at, metadata_vector
        ) VALUES (
            %(id)s, %(name)s, %(category)s, %(body_part)s, %(equipment)s,
            %(muscle_group)s, %(target)s, %(secondary_muscles)s,
            %(instructions_en)s, %(instructions_tr)s,
            %(created_at)s, %(metadata_vector)s
        )
        ON CONFLICT (id) DO UPDATE SET
            name             = EXCLUDED.name,
            category         = EXCLUDED.category,
            body_part        = EXCLUDED.body_part,
            equipment        = EXCLUDED.equipment,
            muscle_group     = EXCLUDED.muscle_group,
            target           = EXCLUDED.target,
            secondary_muscles = EXCLUDED.secondary_muscles,
            instructions_en  = EXCLUDED.instructions_en,
            instructions_tr  = EXCLUDED.instructions_tr,
            created_at       = EXCLUDED.created_at,
            metadata_vector  = EXCLUDED.metadata_vector
        """,
        {
            "id": exercise["id"],
            "name": exercise.get("name"),
            "category": exercise.get("category"),
            "body_part": exercise.get("body_part"),
            "equipment": exercise.get("equipment"),
            "muscle_group": exercise.get("muscle_group"),
            "target": exercise.get("target"),
            "secondary_muscles": exercise.get("secondary_muscles") or [],
            "instructions_en": instructions.get("en"),
            "instructions_tr": instructions.get("tr"),
            "created_at": exercise.get("created_at"),
            "metadata_vector": embedding,
        },
    )

    # Leer binarios de imagen y gif
    image_data = _read_file(media_dir / exercise.get("image", ""))
    gif_data   = _read_file(media_dir / exercise.get("gif_url", ""))

    # Upsert en tabla exercise_media
    cur.execute(
        """
        INSERT INTO exercise_media (exercise_id, image_path, gif_path, image_data, gif_data)
        VALUES (%(exercise_id)s, %(image_path)s, %(gif_path)s, %(image_data)s, %(gif_data)s)
        ON CONFLICT DO NOTHING
        """,
        {
            "exercise_id": exercise["id"],
            "image_path": exercise.get("image"),
            "gif_path": exercise.get("gif_url"),
            "image_data": psycopg2.Binary(image_data) if image_data else None,
            "gif_data":   psycopg2.Binary(gif_data)   if gif_data   else None,
        },
    )


def _read_file(path: Path) -> bytes | None:
    if path and path.exists():
        return path.read_bytes()
    if path:
        log.warning("Fichero no encontrado: %s", path)
    return None


# ──────────────────────────────────────────────
# Punto de entrada principal
# ──────────────────────────────────────────────

def main(json_path: str, media_dir: str, db_url: str, batch_size: int) -> None:
    # Cargar datos
    if json_path.startswith(("http://", "https://")):
        with urllib.request.urlopen(json_path) as response:
            exercises = json.loads(response.read().decode("utf-8"))
    else:
        exercises = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if isinstance(exercises, dict):
        # Soporte para {"exercises": [...]} o un único objeto
        exercises = exercises.get("exercises", [exercises])

    log.info("Ejercicios a cargar: %d", len(exercises))

    # Modelo de embeddings
    log.info("Cargando modelo de embeddings…")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    # Conexión a PostgreSQL
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    media_path = Path(media_dir)
    errors = 0

    for i in tqdm(range(0, len(exercises), batch_size), desc="Cargando batches"):
        batch = exercises[i : i + batch_size]

        # Generar todos los embeddings del batch de una vez (más eficiente)
        texts = [build_metadata_text(ex) for ex in batch]
        embeddings = model.encode(texts, show_progress_bar=False).tolist()

        for exercise, embedding in zip(batch, embeddings):
            try:
                load_exercise(cur, exercise, media_path, embedding)
            except Exception as exc:
                log.error("Error en ejercicio %s: %s", exercise.get("id"), exc)
                conn.rollback()
                errors += 1
                continue

        conn.commit()
        log.debug("Batch %d/%d commiteado", i // batch_size + 1, -(-len(exercises) // batch_size))

    cur.close()
    conn.close()

    log.info("Carga completada. Errores: %d / %d", errors, len(exercises))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga ejercicios en PostgreSQL + pgVector")
    parser.add_argument("--json",       required=True, help="Ruta al fichero JSON de ejercicios")
    parser.add_argument("--media-dir",  default=".",   help="Directorio raíz de imágenes y vídeos")
    parser.add_argument("--db-url",     required=True, help="URL de conexión PostgreSQL")
    parser.add_argument("--batch-size", type=int, default=32, help="Ejercicios por batch de embedding")
    args = parser.parse_args()

    main(args.json, args.media_dir, args.db_url, args.batch_size)
