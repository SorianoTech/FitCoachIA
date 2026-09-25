"""Flujo completo de `/train` contra contenedores reales.

Recorre webhook -> perfil en PostgreSQL -> recuperacion en pgVector -> LLM ->
plan persistido. El LLM, Telegram y el embedder son stubs deterministas
(`tests/fixtures/stub_server.py`); pgVector es real, con el corpus minimo de
`tests/fixtures/exercises_min.sql`.
"""

import json
import os

import asyncpg
import httpx
import pytest
import pytest_asyncio

APP_DB_URL = os.getenv(
    "IT_DB_URL",
    f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
)
VECTOR_DB_URL = os.getenv(
    "IT_VECTOR_DB_URL",
    f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_VECTOR_DB_PORT', '55433')}/fitcoach",
)
STUB_URL = os.getenv("IT_STUB_URL", f"http://localhost:{os.getenv('IT_STUB_PORT', '9999')}")

CHAT_ID = 987654


def _update(update_id: int, text: str) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": CHAT_ID, "type": "private"},
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Ana"},
            "text": text,
        },
    }


@pytest_asyncio.fixture
async def app_db() -> asyncpg.Connection:
    connection = await asyncpg.connect(APP_DB_URL)
    # Cada ejecucion parte de cero para este chat: los tests no deben heredar
    # el plan de una ejecucion anterior.
    await connection.execute("DELETE FROM token_usage WHERE chat_id = $1", CHAT_ID)
    await connection.execute("DELETE FROM training_sessions WHERE chat_id = $1", CHAT_ID)
    await connection.execute("DELETE FROM training_plans WHERE chat_id = $1", CHAT_ID)
    await connection.execute("DELETE FROM conversation_messages WHERE chat_id = $1", CHAT_ID)
    await connection.execute("DELETE FROM interviewer_profiles WHERE chat_id = $1", CHAT_ID)
    await connection.execute("DELETE FROM interview_sessions WHERE chat_id = $1", CHAT_ID)
    try:
        yield connection
    finally:
        await connection.close()


@pytest.fixture
def stub() -> httpx.Client:
    with httpx.Client(base_url=STUB_URL, timeout=10.0) as stub_client:
        stub_client.get("/__reset")
        yield stub_client


def _complete_interview(client: httpx.Client) -> None:
    response = client.post("/webhook/response", json=_update(1, "/interview"))
    assert response.status_code == 200


def _run_train(client: httpx.Client, update_id: int = 2) -> None:
    response = client.post("/webhook/response", json=_update(update_id, "/train"))
    assert response.status_code == 200


@pytest.mark.asyncio
class TestTrainerFlowIntegration:
    async def test_train_persists_a_plan_built_from_real_exercises(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        profile = await app_db.fetchval(
            "SELECT profile FROM interviewer_profiles WHERE chat_id = $1", CHAT_ID
        )
        assert profile is not None, "la entrevista debe dejar el perfil persistido"

        _run_train(client)

        rows = await app_db.fetch(
            "SELECT version, plan, report FROM training_plans WHERE chat_id = $1 ORDER BY version",
            CHAT_ID,
        )
        assert len(rows) == 1
        assert rows[0]["version"] == 1
        assert rows[0]["report"]

    async def test_every_exercise_in_the_plan_exists_in_the_vector_database(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        # La invariante central del agente: el plan sale del catalogo, no de la
        # memoria del modelo.
        _complete_interview(client)
        _run_train(client)

        plan = await app_db.fetchval(
            "SELECT plan FROM training_plans WHERE chat_id = $1 ORDER BY version DESC LIMIT 1",
            CHAT_ID,
        )
        exercise_ids = {
            exercise["exercise_id"]
            for week in json.loads(plan)["weeks"]
            for day in week["days"]
            for exercise in day["exercises"]
        }
        assert exercise_ids

        vector_db = await asyncpg.connect(VECTOR_DB_URL)
        try:
            existing = await vector_db.fetch(
                "SELECT id FROM exercises WHERE id = ANY($1::bigint[])", list(exercise_ids)
            )
        finally:
            await vector_db.close()

        assert {row["id"] for row in existing} == exercise_ids

    async def test_a_second_train_appends_a_new_version(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client, update_id=2)
        _run_train(client, update_id=3)

        versions = await app_db.fetch(
            "SELECT version FROM training_plans WHERE chat_id = $1 ORDER BY version", CHAT_ID
        )

        assert [row["version"] for row in versions] == [1, 2]
        current = await app_db.fetchrow(
            "SELECT status, current_plan_id FROM training_sessions WHERE chat_id = $1", CHAT_ID
        )
        assert current["status"] == "active"
        latest_id = await app_db.fetchval(
            "SELECT id FROM training_plans WHERE chat_id = $1 ORDER BY version DESC LIMIT 1",
            CHAT_ID,
        )
        assert current["current_plan_id"] == latest_id

    async def test_train_turns_are_stored_under_the_trainer_agent(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        # Sin esta separacion, las preguntas al entrenador heredarian toda la
        # transcripcion de la entrevista.
        _complete_interview(client)
        _run_train(client)

        agents = await app_db.fetch(
            "SELECT DISTINCT agent FROM conversation_messages WHERE chat_id = $1", CHAT_ID
        )

        assert {row["agent"] for row in agents} == {"interviewer", "trainer"}

    async def test_token_usage_is_attributed_to_the_trainer(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client)

        total = await app_db.fetchval(
            "SELECT sum(total_tokens) FROM token_usage WHERE chat_id = $1 AND agent = 'trainer'",
            CHAT_ID,
        )

        assert total == 30  # lo que declara el stub por llamada

    async def test_train_without_a_profile_does_not_persist_a_plan(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        # Sin entrevista previa no hay perfil del que partir.
        _run_train(client, update_id=5)

        plans = await app_db.fetchval(
            "SELECT count(*) FROM training_plans WHERE chat_id = $1", CHAT_ID
        )

        assert plans == 0
        texts = [message.get("text", "") for message in stub.get("/__sent").json()]
        assert any("entrevista" in text.lower() for text in texts)

    async def test_the_report_is_delivered_to_telegram(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client)

        texts = [message.get("text", "") for message in stub.get("/__sent").json()]
        report = await app_db.fetchval(
            "SELECT report FROM training_plans WHERE chat_id = $1 ORDER BY version DESC LIMIT 1",
            CHAT_ID,
        )

        assert report in texts
