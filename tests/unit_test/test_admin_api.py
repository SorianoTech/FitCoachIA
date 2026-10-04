import json
import time
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fitcoach.api.admin import admin, admin_access, get_quota_service
from fitcoach.domain.quota import GLOBAL_SCOPE_ID, QuotaAction, QuotaConfig
from fitcoach.infrastructure.config.settings import UsageSettings, get_settings
from fitcoach.infrastructure.database.postgres_quota_repository import PostgresQuotaRepository
from fitcoach.infrastructure.database.session import get_session
from fitcoach.service.quota_service import QuotaService
from tests.unit_test.test_miniapp_auth import settings as auth_settings
from tests.unit_test.test_miniapp_auth import signed
from tests.unit_test.test_quota_service import DEFAULTS, NOW, FakeQuotaRepository

ADMIN_ID = 42
USER_ID = 77
CONFIG = {"token_limit": 1000, "soft_ratio": 0.5, "window_minutes": 60}


def headers(user_id: int) -> dict[str, str]:
    init = signed({"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id})})
    return {"X-Telegram-Init-Data": init}


class Api:
    def __init__(self, client: TestClient, repository: FakeQuotaRepository) -> None:
        self.client = client
        self.repository = repository
        self.service_built = 0


@pytest.fixture
def api() -> Iterator[Api]:
    app = FastAPI()
    app.include_router(admin_access)
    app.include_router(admin)
    repository = FakeQuotaRepository()
    app.dependency_overrides[get_settings] = lambda: auth_settings(
        miniapp_admin_chat_ids=str(ADMIN_ID)
    )

    def build() -> QuotaService:
        state.service_built += 1
        return QuotaService(repository, DEFAULTS, clock=lambda: NOW)

    def no_database() -> None:
        raise AssertionError("database touched")

    app.dependency_overrides[get_quota_service] = build
    app.dependency_overrides[get_session] = no_database
    with TestClient(app) as client:
        state = Api(client, repository)
        yield state


ADMIN_ROUTES = [
    ("GET", "/api/miniapp/admin/settings", None),
    ("PUT", "/api/miniapp/admin/settings", CONFIG),
    ("DELETE", "/api/miniapp/admin/settings", None),
    ("GET", "/api/miniapp/admin/users", None),
    ("GET", f"/api/miniapp/admin/users/{USER_ID}", None),
    ("PUT", f"/api/miniapp/admin/users/{USER_ID}", CONFIG),
    ("DELETE", f"/api/miniapp/admin/users/{USER_ID}", None),
    ("GET", "/api/miniapp/admin/audit", None),
]


class TestAuthorization:
    @pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
    def test_unsigned_request_is_rejected(
        self, api: Api, method: str, path: str, body: dict[str, object] | None
    ) -> None:
        response = api.client.request(method, path, json=body)
        assert response.status_code == 401
        assert api.service_built == 0

    @pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
    def test_valid_non_admin_is_forbidden_before_database(
        self, api: Api, method: str, path: str, body: dict[str, object] | None
    ) -> None:
        response = api.client.request(method, path, json=body, headers=headers(USER_ID))
        assert response.status_code == 403
        assert api.service_built == 0
        assert api.repository.configs == {}
        assert api.repository.entries == []

    def test_forged_signature_is_rejected(self, api: Api) -> None:
        forged = headers(ADMIN_ID)["X-Telegram-Init-Data"].replace("42", "43")
        response = api.client.get(
            "/api/miniapp/admin/settings", headers={"X-Telegram-Init-Data": forged}
        )
        assert response.status_code == 401

    def test_access_reports_membership_without_database(self, api: Api) -> None:
        assert api.client.get("/api/miniapp/admin/access", headers=headers(ADMIN_ID)).json() == {
            "is_admin": True
        }
        assert api.client.get("/api/miniapp/admin/access", headers=headers(USER_ID)).json() == {
            "is_admin": False
        }
        assert api.client.get("/api/miniapp/admin/access").status_code == 401
        assert api.service_built == 0

    def test_without_configured_admins_nobody_is_admin(self, api: Api) -> None:
        app = api.client.app
        assert isinstance(app, FastAPI)
        app.dependency_overrides[get_settings] = lambda: auth_settings()
        response = api.client.get("/api/miniapp/admin/settings", headers=headers(ADMIN_ID))
        assert response.status_code == 403
        assert api.client.get("/api/miniapp/admin/access", headers=headers(ADMIN_ID)).json() == {
            "is_admin": False
        }


class TestSettings:
    def test_get_put_delete_global(self, api: Api) -> None:
        defaults = DEFAULTS.model_dump()
        auth = headers(ADMIN_ID)
        response = api.client.get("/api/miniapp/admin/settings", headers=auth)
        assert response.json() == {"global": None, "defaults": defaults, "effective": defaults}
        response = api.client.put("/api/miniapp/admin/settings", json=CONFIG, headers=auth)
        assert response.json() == {"global": CONFIG, "defaults": defaults, "effective": CONFIG}
        response = api.client.delete("/api/miniapp/admin/settings", headers=auth)
        assert response.json() == {"global": None, "defaults": defaults, "effective": defaults}
        assert [(e.actor_chat_id, e.subject_chat_id) for e in api.repository.entries] == [
            (ADMIN_ID, GLOBAL_SCOPE_ID),
            (ADMIN_ID, GLOBAL_SCOPE_ID),
        ]

    @pytest.mark.parametrize(
        "body",
        [
            {**CONFIG, "token_limit": 0},
            {**CONFIG, "token_limit": 1_000_000_001},
            {**CONFIG, "soft_ratio": 0},
            {**CONFIG, "soft_ratio": 1.5},
            {**CONFIG, "window_minutes": 525_601},
            {**CONFIG, "token_limit": "1000"},
            {**CONFIG, "chat_id": 1},
            {"token_limit": 1},
        ],
    )
    def test_invalid_config_is_rejected(self, api: Api, body: dict[str, object]) -> None:
        auth = headers(ADMIN_ID)
        assert (
            api.client.put("/api/miniapp/admin/settings", json=body, headers=auth).status_code
            == 422
        )
        assert (
            api.client.put(
                f"/api/miniapp/admin/users/{USER_ID}", json=body, headers=auth
            ).status_code
            == 422
        )
        assert api.repository.configs == {}


class TestUsers:
    def test_override_lifecycle_and_status_shape(self, api: Api) -> None:
        auth = headers(ADMIN_ID)
        api.client.put("/api/miniapp/admin/settings", json=CONFIG, headers=auth)
        override = {"token_limit": 500, "soft_ratio": 1.0, "window_minutes": 10}
        response = api.client.put(
            f"/api/miniapp/admin/users/{USER_ID}", json=override, headers=auth
        )
        assert response.json() == {
            "chat_id": USER_ID,
            "used_tokens": 0,
            "hard_tokens": 500,
            "soft_tokens": 500,
            "window_minutes": 10,
            "source": "user",
            "override": override,
        }
        response = api.client.delete(f"/api/miniapp/admin/users/{USER_ID}", headers=auth)
        assert response.json()["source"] == "global"
        assert response.json()["override"] is None
        api.client.delete("/api/miniapp/admin/settings", headers=auth)
        response = api.client.get(f"/api/miniapp/admin/users/{USER_ID}", headers=auth)
        assert response.json()["source"] == "environment"
        audit = api.client.get("/api/miniapp/admin/audit", headers=auth).json()
        assert [entry["action"] for entry in audit] == [
            QuotaAction.CLEAR_GLOBAL,
            QuotaAction.CLEAR_USER,
            QuotaAction.SET_USER,
            QuotaAction.SET_GLOBAL,
        ]
        assert audit[1]["before"] == override
        assert audit[1]["subject_chat_id"] == USER_ID

    def test_list_users_pagination_contract(self, api: Api) -> None:
        api.repository.known = {1, 2, 3}
        auth = headers(ADMIN_ID)
        body = api.client.get("/api/miniapp/admin/users?limit=2", headers=auth).json()
        assert (body["offset"], body["limit"], body["has_more"]) == (0, 2, True)
        assert [user["chat_id"] for user in body["users"]] == [1, 2]
        assert set(body["users"][0]) == {
            "chat_id",
            "used_tokens",
            "hard_tokens",
            "soft_tokens",
            "window_minutes",
            "source",
            "override",
        }
        body = api.client.get("/api/miniapp/admin/users", headers=auth).json()
        assert (body["limit"], body["has_more"]) == (25, False)

    @pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
    def test_list_users_bounds(self, api: Api, query: str) -> None:
        response = api.client.get(f"/api/miniapp/admin/users?{query}", headers=headers(ADMIN_ID))
        assert response.status_code == 422

    @pytest.mark.parametrize("chat_id", ["0", "-5", str(2**63), "abc"])
    def test_user_id_must_be_positive_signed64(self, api: Api, chat_id: str) -> None:
        auth = headers(ADMIN_ID)
        assert (
            api.client.get(f"/api/miniapp/admin/users/{chat_id}", headers=auth).status_code == 422
        )
        assert (
            api.client.put(
                f"/api/miniapp/admin/users/{chat_id}", json=CONFIG, headers=auth
            ).status_code
            == 422
        )

    def test_audit_limit_is_bounded(self, api: Api) -> None:
        auth = headers(ADMIN_ID)
        assert api.client.get("/api/miniapp/admin/audit?limit=101", headers=auth).status_code == 422


@pytest.mark.asyncio
async def test_get_quota_service_uses_postgres_and_environment_defaults() -> None:
    usage = UsageSettings(_env_file=None, token_limit=2_000, soft_ratio=0.25, window_minutes=30)
    service = await get_quota_service(MagicMock(), usage)
    assert isinstance(service._repository, PostgresQuotaRepository)
    assert service._defaults == QuotaConfig(token_limit=2_000, soft_ratio=0.25, window_minutes=30)
    assert service._defaults.to_limits() == usage.to_limits()
