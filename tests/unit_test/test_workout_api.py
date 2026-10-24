from collections.abc import Iterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from fitcoach.api.miniapp import get_workout_service, router
from fitcoach.api.miniapp_auth import get_miniapp_chat_id
from fitcoach.domain.workout import (
    WorkoutConflictError,
    WorkoutNotFoundError,
    WorkoutProgress,
    WorkoutValidationError,
)
from tests.unit_test.test_workout import workout


@pytest.fixture
def api() -> Iterator[tuple[TestClient, AsyncMock]]:
    app = FastAPI()
    app.include_router(router)
    service = AsyncMock()
    app.dependency_overrides[get_miniapp_chat_id] = lambda: 123
    app.dependency_overrides[get_workout_service] = lambda: service
    with TestClient(app) as client:
        yield client, service


def test_list_detail_start_patch_contract(api: tuple[TestClient, AsyncMock]) -> None:
    client, service = api
    session = workout(completed=False)
    service.list_sessions.return_value = [session]
    service.get.return_value = session
    service.start.return_value = session
    service.update.return_value = session
    assert client.get("/api/miniapp/sessions").json() == [session.model_dump(mode="json")]
    detail = client.get("/api/miniapp/sessions/1")
    assert detail.status_code == 200
    assert "chat_id" not in detail.json()
    response = client.post(
        "/api/miniapp/sessions",
        json={
            "request_id": str(uuid4()),
            "plan_id": 1,
            "week": 1,
            "day": 1,
        },
    )
    assert response.status_code == 200
    service.start.assert_awaited_once()
    assert service.start.call_args.args[0] == 123
    response = client.patch(
        "/api/miniapp/sessions/1",
        json={
            "revision": 0,
            "status": "in_progress",
            "exercises": [item.model_dump(mode="json") for item in session.exercises],
        },
    )
    assert response.status_code == 200
    service.update.assert_awaited_once()
    assert service.update.call_args.args[:2] == (123, 1)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (WorkoutNotFoundError("missing"), 404),
        (WorkoutConflictError("revision"), 409),
        (WorkoutValidationError("invalid"), 422),
    ],
)
def test_domain_errors_are_explicit_http_errors(
    api: tuple[TestClient, AsyncMock], error: Exception, code: int
) -> None:
    client, service = api
    service.get.side_effect = error
    response = client.get("/api/miniapp/sessions/1")
    assert response.status_code == code
    assert response.json()["detail"] == str(error)


def test_schema_rejects_invalid_json_before_service(api: tuple[TestClient, AsyncMock]) -> None:
    client, service = api
    assert (
        client.post(
            "/api/miniapp/sessions",
            json={
                "request_id": "bad",
                "plan_id": 1,
                "week": 5,
                "day": 1,
                "chat_id": 999,
            },
        ).status_code
        == 422
    )
    assert client.get("/api/miniapp/sessions/0").status_code == 422
    assert (
        client.patch(
            "/api/miniapp/sessions/1",
            json={
                "revision": -1,
                "status": "completed",
                "exercises": [],
            },
        ).status_code
        == 422
    )
    service.start.assert_not_awaited()
    service.update.assert_not_awaited()


def test_no_plan_is_404_and_progress_empty_is_valid(api: tuple[TestClient, AsyncMock]) -> None:
    client, service = api
    service.bootstrap.side_effect = WorkoutNotFoundError("No current training plan")
    assert client.get("/api/miniapp/bootstrap").status_code == 404
    service.progress.return_value = WorkoutProgress(completed_sessions=0, exercises=[])
    assert client.get("/api/miniapp/progress").json() == {
        "completed_sessions": 0,
        "exercises": [],
        "history_limit": 100,
        "history_truncated": False,
    }


def test_authentication_rejects_before_constructing_database_dependencies() -> None:
    app = FastAPI()
    app.include_router(router)

    def unauthenticated() -> int:
        raise HTTPException(status_code=401, detail="Unauthorized")

    def forbidden_service() -> None:
        pytest.fail("Unauthenticated requests must not initialize journal resources")

    app.dependency_overrides[get_miniapp_chat_id] = unauthenticated
    app.dependency_overrides[get_workout_service] = forbidden_service
    with TestClient(app) as client:
        for path in ["/bootstrap", "/sessions", "/sessions/1", "/progress"]:
            assert client.get(f"/api/miniapp{path}").status_code == 401
        assert client.post("/api/miniapp/sessions", json={}).status_code == 401
        assert client.patch("/api/miniapp/sessions/1", json={}).status_code == 401
