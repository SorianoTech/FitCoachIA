from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fitcoach.api.miniapp import router
from fitcoach.api.miniapp_auth import get_miniapp_chat_id
from fitcoach.infrastructure.database.session import get_session
from tests.it.test_training_repository import CHAT_ID
from tests.it.test_training_repository import training_factory as training_factory


@pytest.mark.asyncio
async def test_real_authenticated_journal_routes(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = FastAPI()
    app.include_router(router)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with training_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_miniapp_chat_id] = lambda: CHAT_ID
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        bootstrap = await client.get("/api/miniapp/bootstrap")
        assert bootstrap.status_code == 200
        assert set(bootstrap.json()) == {
            "plan_id",
            "version",
            "plan",
            "cycle",
            "current_week",
            "calendar_status",
        }
        start = await client.post(
            "/api/miniapp/sessions",
            json={
                "request_id": str(uuid4()),
                "plan_id": bootstrap.json()["plan_id"],
                "week": 1,
                "day": 1,
            },
        )
        assert start.status_code == 200
        session = start.json()
        assert "chat_id" not in session
        assert session["prescription"] == bootstrap.json()["plan"]["weeks"][0]["days"][0]
        assert (await client.get("/api/miniapp/sessions")).json() == [session]
        entries = session["exercises"]
        for exercise in entries:
            for recorded in exercise["sets"]:
                recorded.update(reps=8, completed=True, weight_kg=0.0, rpe=7.0)
        patch = {"revision": 0, "status": "completed", "exercises": entries}
        updated = await client.patch(f"/api/miniapp/sessions/{session['id']}", json=patch)
        assert updated.status_code == 200
        assert updated.json()["revision"] == 1
        assert updated.json()["completed_at"] is not None
        stale = await client.patch(f"/api/miniapp/sessions/{session['id']}", json=patch)
        assert stale.status_code == 409
        progress = await client.get("/api/miniapp/progress")
        assert progress.status_code == 200
        history = progress.json()["exercises"][0]["history"][0]
        assert history["total_reps"] == 24
        assert history["max_weight_kg"] == 0.0
        assert history["average_rpe"] == 7.0
        app.dependency_overrides[get_miniapp_chat_id] = lambda: CHAT_ID + 1
        assert (await client.get(f"/api/miniapp/sessions/{session['id']}")).status_code == 404
        assert (await client.get("/api/miniapp/bootstrap")).status_code == 404
        assert (await client.get("/api/miniapp/sessions")).json() == []
