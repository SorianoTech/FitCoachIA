import json
import os

import asyncpg
import httpx
import pytest

DATABASE_URL = os.getenv(
    "IT_DB_URL",
    f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
)
VECTOR_DATABASE_URL = os.getenv(
    "IT_VECTOR_DB_URL",
    f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_VECTOR_DB_PORT', '55433')}/fitcoach",
)


@pytest.mark.asyncio
async def test_admin_approval_publishes_exercise_for_rag(client: httpx.Client) -> None:
    proposal = {
        "name": "backpack row",
        "category": "back",
        "body_part": "back",
        "equipment": "body weight",
        "target": "lats",
        "secondary_muscles": ["biceps"],
        "instructions_en": (
            "Hold the backpack securely, hinge forward, and row it toward the torso."
        ),
        "quality": {
            "validity": "valid",
            "confidence": 0.91,
            "rationale": "It is a coherent loaded horizontal pulling movement.",
            "safety_notes": ["Secure the backpack before starting."],
        },
    }
    database = await asyncpg.connect(DATABASE_URL)
    try:
        submission_id = await database.fetchval(
            """
            INSERT INTO exercise_submissions (
                chat_id, raw_description, proposal, status, model
            ) VALUES ($1, $2, $3::jsonb, 'pending', $4)
            RETURNING id
            """,
            7001,
            "remo con mochila",
            json.dumps(proposal),
            "curator-test",
        )
    finally:
        await database.close()

    response = client.post(
        "/webhook/response",
        json={
            "update_id": 910001,
            "message": {
                "message_id": 42,
                "date": 0,
                "chat": {"id": 9001, "type": "private"},
                "from": {"id": 9001, "is_bot": False, "first_name": "Admin"},
                "text": f"/approve_exercise {submission_id}",
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    database = await asyncpg.connect(DATABASE_URL)
    vector_database = await asyncpg.connect(VECTOR_DATABASE_URL)
    try:
        stored = await database.fetchrow(
            """
            SELECT status, reviewed_by, published_exercise_id
            FROM exercise_submissions
            WHERE id = $1
            """,
            submission_id,
        )
        assert stored is not None
        assert stored["status"] == "approved"
        assert stored["reviewed_by"] == 9001
        exercise_id = stored["published_exercise_id"]
        published = await vector_database.fetchrow(
            """
            SELECT e.name, e.target, e.equipment, e.metadata_vector IS NOT NULL AS embedded
            FROM exercise_publications p
            JOIN exercises e ON e.id = p.exercise_id
            WHERE p.submission_id = $1
            """,
            submission_id,
        )
        assert exercise_id is not None
        assert published is not None
        assert dict(published) == {
            "name": "backpack row",
            "target": "lats",
            "equipment": "body weight",
            "embedded": True,
        }
    finally:
        await vector_database.close()
        await database.close()
