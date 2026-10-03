from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from telegram import Bot, User
from telegram.error import NetworkError

from fitcoach.api.miniapp_actions import miniapp_actions
from fitcoach.api.miniapp_auth import get_miniapp_chat_id
from fitcoach.api.webhook import get_training_service
from fitcoach.domain.training_lifecycle import TrainingWorkflow
from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.infrastructure.database.dependencies import get_conversation_repository
from fitcoach.infrastructure.database.session import get_session
from fitcoach.repository.conversation_repository import StoredTrainingPlan
from fitcoach.service.training_service import TrainingService
from fitcoach.service.training_view import view_keyboard
from tests.unit_test.conftest import build_plan_payload


@pytest.fixture
def controls(monkeypatch: pytest.MonkeyPatch) -> tuple:
    from fitcoach.domain.trainer_plan import TrainingPlan

    app = FastAPI()
    app.include_router(miniapp_actions)
    bot = AsyncMock(spec=Bot)
    bot.get_me.return_value = User(1, "FitCoach", True, username="fitcoach_test_bot")
    conversation = AsyncMock()
    conversation.get_current_plan.return_value = StoredTrainingPlan(
        10, 1, TrainingPlan.model_validate(build_plan_payload()), "report"
    )
    workflow_repository = AsyncMock()
    workflow_repository.get_workflow.return_value = None
    monkeypatch.setattr(
        "fitcoach.api.miniapp_actions.PostgresTrainingRepository",
        lambda _: workflow_repository,
    )
    service = AsyncMock(spec=TrainingService)
    service.handle.return_value = ["Elige el ejercicio."]
    service.keyboard.return_value = None
    app.dependency_overrides[get_miniapp_chat_id] = lambda: 99
    app.dependency_overrides[get_conversation_repository] = lambda: conversation
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_training_service] = lambda: service
    app.dependency_overrides[get_bot] = lambda: bot
    return TestClient(app), conversation, workflow_repository, service, bot


@pytest.mark.parametrize(
    ("action", "command"), [("swap", "/train cambiar"), ("review", "/train revisar")]
)
def test_handoff_reuses_workflow_and_delivers_real_controls(
    controls: tuple, action: str, command: str
) -> None:
    client, _, _, service, bot = controls
    response = client.post("/api/miniapp/actions", json={"plan_id": 10, "action": action})
    assert response.status_code == 200
    service.handle.assert_awaited_once_with(99, command)
    bot.send_message.assert_awaited_once_with(
        chat_id=99, text="Elige el ejercicio.", reply_markup=None
    )
    assert response.json()["bot_url"] == "https://t.me/fitcoach_test_bot"


def test_stale_or_missing_plan_cannot_open_workflow(controls: tuple) -> None:
    client, conversation, _, service, bot = controls
    assert (
        client.post("/api/miniapp/actions", json={"plan_id": 11, "action": "swap"}).status_code
        == 409
    )
    conversation.get_current_plan.return_value = None
    assert (
        client.post("/api/miniapp/actions", json={"plan_id": 10, "action": "swap"}).status_code
        == 404
    )
    service.handle.assert_not_awaited()
    bot.send_message.assert_not_awaited()


def test_other_pending_workflow_is_not_discarded(controls: tuple) -> None:
    client, _, repository, service, _ = controls
    repository.get_workflow.return_value = TrainingWorkflow(
        id=1, kind="renewal", base_plan_id=10, state="awaiting_confirmation"
    )
    response = client.post("/api/miniapp/actions", json={"plan_id": 10, "action": "swap"})
    assert response.status_code == 409
    service.handle.assert_not_awaited()


def test_delivery_failure_is_explicit_not_success(controls: tuple) -> None:
    client, _, _, _, bot = controls
    bot.send_message.side_effect = NetworkError("unavailable")
    response = client.post("/api/miniapp/actions", json={"plan_id": 10, "action": "swap"})
    assert response.status_code == 502


def test_visual_access_is_optional_and_uses_web_app_info() -> None:
    plain = view_keyboard(10)
    assert not any(button.web_app for row in plain.inline_keyboard for button in row)
    enabled = view_keyboard(10, miniapp_url="https://example.com/miniapp/")
    assert enabled.inline_keyboard[0][0].web_app.url == "https://example.com/miniapp/"


def test_menu_registration_enables_miniapp(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from telegram import MenuButtonWebApp

    import fitcoach.main as main
    from tests.unit_test.test_miniapp_auth import settings

    bot = AsyncMock(spec=Bot)
    bot.get_webhook_info.return_value.url = "https://example.com/webhook/response"
    bot.get_webhook_info.return_value.last_error_message = None
    monkeypatch.setattr(main, "get_bot", AsyncMock(return_value=bot))
    asyncio.run(
        main._register_webhook(main.app, settings(miniapp_url="https://example.com/miniapp/"))
    )
    button = bot.set_chat_menu_button.await_args.kwargs["menu_button"]
    assert isinstance(button, MenuButtonWebApp)
    assert button.web_app.url == "https://example.com/miniapp/"


def test_miniapp_auth_responses_are_not_cacheable() -> None:
    from fitcoach.infrastructure.config.settings import get_settings
    from fitcoach.main import app
    from tests.unit_test.test_miniapp_auth import settings

    app.dependency_overrides[get_settings] = lambda: settings()
    try:
        response = TestClient(app).get("/api/miniapp/bootstrap")
    finally:
        app.dependency_overrides.pop(get_settings)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
