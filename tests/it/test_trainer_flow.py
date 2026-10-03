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


def _callback(update_id: int, data: str) -> dict[str, object]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"click-{update_id}",
            "chat_instance": "test-chat",
            "data": data,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Ana"},
            "message": {
                "message_id": 100,
                "date": 0,
                "text": "propuesta",
                "chat": {"id": CHAT_ID, "type": "private"},
            },
        },
    }


@pytest_asyncio.fixture
async def app_db() -> asyncpg.Connection:
    connection = await asyncpg.connect(APP_DB_URL)
    # Cada ejecucion parte de cero para este chat: los tests no deben heredar
    # el plan de una ejecucion anterior.
    await connection.execute(
        "DELETE FROM processed_updates WHERE update_id = ANY($1::bigint[])",
        [1, 2, 3, 5, *range(20, 40)],
    )
    await connection.execute("DELETE FROM token_usage WHERE chat_id = $1", CHAT_ID)
    await connection.execute("DELETE FROM training_sessions WHERE chat_id = $1", CHAT_ID)
    await connection.execute("DELETE FROM training_plans WHERE chat_id = $1", CHAT_ID)
    await connection.execute("DELETE FROM training_mesocycles WHERE chat_id = $1", CHAT_ID)
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
    async def test_week_request_sends_only_real_selector_and_asks_reason(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client)
        before = len(stub.get("/__sent").json())
        client.post(
            "/webhook/response", json=_update(20, "quiero cambiar un ejercicio de la semana 1")
        )
        messages = stub.get("/__sent").json()[before:]
        assert len(messages) == 1
        assert "¿Qué ejercicio de la semana 1 quieres cambiar?" in messages[0]["text"]
        assert "exercise_swap" not in messages[0]["text"]
        keyboard = json.loads(messages[0]["reply_markup"])["inline_keyboard"]
        button = next(
            button
            for row in keyboard
            for button in row
            if button["callback_data"].startswith("tr:exercise:")
        )
        client.post("/webhook/response", json=_callback(21, button["callback_data"]))
        assert stub.get("/__sent").json()[-1]["text"] == "¿Por qué quieres cambiarlo?"
        payload = json.loads(
            await app_db.fetchval(
                "SELECT payload FROM training_workflows WHERE chat_id=$1", CHAT_ID
            )
        )
        assert payload["answers"]["swap_week"] == "1"
        assert payload["swap"] is None

    @pytest.mark.parametrize("natural", [True, False])
    async def test_swap_request_uses_buttons_and_keeps_current_plan(
        self,
        client: httpx.Client,
        app_db: asyncpg.Connection,
        stub: httpx.Client,
        natural: bool,
    ) -> None:
        _complete_interview(client)
        _run_train(client)
        text = "Quiero cambiar el press de banca, prefiero otro ejercicio"
        calls_before = stub.get("/__counts").json()["llm"]
        client.post("/webhook/response", json=_update(20, text if natural else "/train cambiar"))
        sent = stub.get("/__sent").json()[-1]
        assert sent["text"] == "¿Qué ejercicio quieres cambiar? Elige abajo."
        keyboard = json.loads(sent["reply_markup"])["inline_keyboard"]
        button = next(
            button
            for row in keyboard
            for button in row
            if button["callback_data"].startswith("tr:exercise:")
            and button["callback_data"].endswith(":1")
        )
        client.post("/webhook/response", json=_callback(21, button["callback_data"]))
        keyboard = json.loads(stub.get("/__sent").json()[-1]["reply_markup"])["inline_keyboard"]
        week = next(
            button
            for row in keyboard
            for button in row
            if button["callback_data"].startswith("tr:week:")
            and button["callback_data"].endswith(":2")
        )
        client.post("/webhook/response", json=_callback(22, week["callback_data"]))
        if not natural:
            keyboard = json.loads(stub.get("/__sent").json()[-1]["reply_markup"])["inline_keyboard"]
            reason = next(
                button
                for row in keyboard
                for button in row
                if button["callback_data"].endswith(":preference")
            )
            client.post("/webhook/response", json=_callback(23, reason["callback_data"]))
        flow = await app_db.fetchrow(
            "SELECT state, payload FROM training_workflows WHERE chat_id=$1", CHAT_ID
        )
        assert flow["state"] == "awaiting_confirmation"
        payload = json.loads(flow["payload"])
        assert payload["swap"]["reason"] == (text if natural else "Prefiero otro ejercicio")
        assert payload["swap"]["from_week"] == 2
        assert payload["swap"]["reason_source"] == ("free_text" if natural else "preference_button")
        calls_after = stub.get("/__counts").json()["llm"]
        assert calls_after - calls_before == (3 if natural else 1)
        assert (
            await app_db.fetchval("SELECT count(*) FROM training_plans WHERE chat_id=$1", CHAT_ID)
            == 1
        )

    async def test_quick_closure_generates_draft_with_one_button(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client)
        client.post("/webhook/response", json=_update(20, "/train"))
        sent = stub.get("/__sent").json()[-1]
        keyboard = json.loads(sent["reply_markup"])["inline_keyboard"]
        assert keyboard[0][0]["text"] == "Terminé y todo bien"
        client.post("/webhook/response", json=_callback(21, keyboard[0][0]["callback_data"]))
        flow = await app_db.fetchrow(
            "SELECT state, payload FROM training_workflows WHERE chat_id=$1", CHAT_ID
        )
        payload = json.loads(flow["payload"])
        assert flow["state"] == "awaiting_confirmation"
        assert payload["answers"]["quick_review"] == "true"
        assert "no informado" in payload["review"]["adherence"]
        assert payload["review"]["safety_hold"] is False
        assert (
            await app_db.fetchval("SELECT count(*) FROM training_plans WHERE chat_id=$1", CHAT_ID)
            == 1
        )
        assert await app_db.fetchval(
            "SELECT completed_at IS NOT NULL FROM training_mesocycles WHERE chat_id=$1", CHAT_ID
        )
        assert "TU SIGUIENTE MESOCICLO" in stub.get("/__sent").json()[-1]["text"]

    async def test_review_draft_and_repeated_confirmation(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client)
        before = await app_db.fetchrow(
            "SELECT current_plan_id FROM training_sessions WHERE chat_id = $1", CHAT_ID
        )
        old_cycle = await app_db.fetchval(
            "SELECT mesocycle_id FROM training_plans WHERE id = $1", before["current_plan_id"]
        )
        for update_id, text in enumerate(
            [
                "/train",
                "sí",
                "He realizado todas las sesiones y mejoran las repeticiones. "
                "Buena recuperación y sueño sin cambios, sin molestias nuevas. "
                "Quiero mantener los ejercicios, sin cambios de disponibilidad.",
            ],
            20,
        ):
            response = client.post("/webhook/response", json=_update(update_id, text))
            assert response.status_code == 200
        flow = await app_db.fetchrow(
            "SELECT id, state, payload FROM training_workflows WHERE chat_id = $1", CHAT_ID
        )
        assert flow["state"] == "awaiting_confirmation"
        assert json.loads(flow["payload"])["draft"] is not None
        sent = stub.get("/__sent").json()
        card = sent[-1]
        assert "TU SIGUIENTE MESOCICLO" in card["text"]
        assert "Borrador " not in card["text"]
        assert "Contexto propuesto" not in card["text"]
        assert len(card["text"]) <= 4096
        keyboard = json.loads(card["reply_markup"])["inline_keyboard"]
        details_button = next(
            button
            for row in keyboard
            for button in row
            if button["callback_data"].startswith("tr:details:")
        )
        client.post("/webhook/response", json=_callback(32, details_button["callback_data"]))
        shown = [message["text"] for message in stub.get("/__sent").json()]
        assert "PLAN COMPLETO PROPUESTO" in shown
        assert any("SEMANA 4" in text for text in shown)
        assert shown[-1].startswith("TU SIGUIENTE MESOCICLO")
        assert (
            await app_db.fetchval(
                "SELECT current_plan_id FROM training_sessions WHERE chat_id = $1", CHAT_ID
            )
            == before["current_plan_id"]
        )
        client.post("/webhook/response", json=_update(30, "/train cambiar 1 1 preferencia"))
        client.post("/webhook/response", json=_update(31, f"/train elegir {flow['id']} 1"))
        for update_id in (28, 29):
            response = client.post(
                "/webhook/response", json=_update(update_id, f"/train confirmar {flow['id']}")
            )
            assert response.status_code == 200
        plans = await app_db.fetch(
            "SELECT version, mesocycle_id FROM training_plans WHERE chat_id = $1 ORDER BY version",
            CHAT_ID,
        )
        assert [row["version"] for row in plans] == [1, 2]
        assert plans[1]["mesocycle_id"] != old_cycle
        payload = await app_db.fetchval(
            "SELECT payload FROM training_workflows WHERE id=$1", flow["id"]
        )
        assert len(json.loads(payload)["generation_traces"]) == 2

    async def test_swap_creates_version_in_same_cycle_after_selection(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client)
        before = await app_db.fetchrow(
            "SELECT plan, mesocycle_id FROM training_plans WHERE chat_id = $1", CHAT_ID
        )
        client.post("/webhook/response", json=_update(20, "/train cambiar 1 2 preferencia"))
        flow = await app_db.fetchrow(
            "SELECT id, state, payload FROM training_workflows WHERE chat_id = $1", CHAT_ID
        )
        assert flow["state"] == "awaiting_confirmation"
        revision = json.loads(flow["payload"])["revision"]
        controls = json.loads(stub.get("/__sent").json()[-1]["reply_markup"])
        assert (
            controls["inline_keyboard"][0][0]["callback_data"]
            == f"tr:select:{flow['id']}:{revision}:1"
        )
        client.post("/webhook/response", json=_callback(21, f"tr:select:{flow['id']}:{revision}:1"))
        payload = json.loads(
            await app_db.fetchval("SELECT payload FROM training_workflows WHERE id=$1", flow["id"])
        )
        stale = f"tr:accept:{flow['id']}:{revision}"
        client.post("/webhook/response", json=_callback(23, stale))
        assert (
            await app_db.fetchval("SELECT count(*) FROM training_plans WHERE chat_id=$1", CHAT_ID)
            == 1
        )
        data = f"tr:accept:{flow['id']}:{payload['revision']}"
        client.post("/webhook/response", json=_callback(22, data))
        client.post("/webhook/response", json=_callback(24, data))
        after = await app_db.fetchrow(
            "SELECT version, plan, mesocycle_id FROM training_plans WHERE chat_id = $1 ORDER BY version DESC LIMIT 1",
            CHAT_ID,
        )
        assert after["version"] == 2
        assert after["mesocycle_id"] == before["mesocycle_id"]
        old_plan, new_plan = json.loads(before["plan"]), json.loads(after["plan"])
        assert new_plan["weeks"][0] == old_plan["weeks"][0]
        assert new_plan["weeks"][1]["days"][0]["exercises"][0]["exercise_id"] == 6
        assert new_plan["weeks"][3]["days"][0]["exercises"][0]["rpe"] <= 6
        trace = await app_db.fetchrow(
            "SELECT model, skill_name, retrieved_exercise_ids FROM training_plans WHERE chat_id=$1 ORDER BY version DESC LIMIT 1",
            CHAT_ID,
        )
        assert trace["model"] == "test-model"
        assert trace["skill_name"] == "trainer-swap"
        assert 6 in json.loads(trace["retrieved_exercise_ids"])

    async def test_a_question_answers_from_the_plan_without_modifying_it(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client)
        before = await app_db.fetchrow(
            "SELECT id, version, plan FROM training_plans WHERE chat_id = $1", CHAT_ID
        )
        embedding_calls = stub.get("/__counts").json()["embed"]
        assert embedding_calls > 0

        response = client.post("/webhook/response", json=_update(3, "¿Cuánto descanso?"))

        assert response.status_code == 200
        assert stub.get("/__counts").json()["embed"] == embedding_calls
        plans = await app_db.fetch(
            "SELECT id, version, plan FROM training_plans WHERE chat_id = $1", CHAT_ID
        )
        assert len(plans) == 1
        assert plans[0] == before
        texts = [message.get("text", "") for message in stub.get("/__sent").json()]
        assert "El plan indica 120 segundos de descanso." in texts
        latest = await app_db.fetchrow(
            """SELECT role, content, agent
               FROM conversation_messages WHERE chat_id = $1 ORDER BY id DESC LIMIT 1""",
            CHAT_ID,
        )
        assert latest["agent"] == "trainer"
        assert latest["role"] == "assistant"
        assert latest["content"] == "El plan indica 120 segundos de descanso."

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
            """
            SELECT version, plan, report, model, skill_name, prompt_hash, skill_hash,
                   retrieved_exercise_ids
            FROM training_plans
            WHERE chat_id = $1
            ORDER BY version
            """,
            CHAT_ID,
        )
        assert len(rows) == 1
        assert rows[0]["version"] == 1
        assert rows[0]["report"]
        assert rows[0]["model"]
        assert rows[0]["skill_name"] == "trainer"
        assert len(rows[0]["prompt_hash"]) == 64
        assert len(rows[0]["skill_hash"]) == 64
        assert json.loads(rows[0]["retrieved_exercise_ids"])

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

    async def test_a_second_train_opens_review_without_replacing_the_plan(
        self, client: httpx.Client, app_db: asyncpg.Connection, stub: httpx.Client
    ) -> None:
        _complete_interview(client)
        _run_train(client, update_id=2)
        _run_train(client, update_id=3)

        versions = await app_db.fetch(
            "SELECT version FROM training_plans WHERE chat_id = $1 ORDER BY version", CHAT_ID
        )

        assert [row["version"] for row in versions] == [1]
        pending = await app_db.fetchval(
            "SELECT state FROM training_workflows WHERE chat_id = $1", CHAT_ID
        )
        assert pending == "reviewing"
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
