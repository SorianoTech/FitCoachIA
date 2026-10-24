from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from rag_doc.api import get_answer_service, router
from rag_doc.limits import RateLimiter
from rag_doc.service import Answer


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.day = date(2026, 1, 1)


def _limiter(clock: Clock, per_minute: int = 2, daily_cap: int = 100) -> RateLimiter:
    return RateLimiter(per_minute, daily_cap, clock=lambda: clock.now, today=lambda: clock.day)


def test_allows_up_to_the_per_minute_limit_then_rejects() -> None:
    limiter = _limiter(Clock())

    assert [limiter.check("a") for _ in range(3)] == [None, None, "rate"]


def test_limit_is_per_client() -> None:
    limiter = _limiter(Clock(), per_minute=1)

    assert limiter.check("a") is None
    assert limiter.check("b") is None


def test_window_slides_after_a_minute() -> None:
    clock = Clock()
    limiter = _limiter(clock, per_minute=1)
    limiter.check("a")

    clock.now = 61
    assert limiter.check("a") is None


def test_daily_cap_rejects_all_clients_until_next_day() -> None:
    clock = Clock()
    limiter = _limiter(clock, per_minute=10, daily_cap=2)
    limiter.check("a")
    limiter.check("b")

    assert limiter.check("c") == "daily"

    clock.day += timedelta(days=1)
    assert limiter.check("c") is None


class _Service:
    async def ask(self, question: str, history: list[dict[str, str]]) -> Answer:
        return Answer(answer="ok", sources=[])


def _client(limiter: RateLimiter) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_answer_service] = lambda: _Service()
    app.state.rate_limiter = limiter
    return TestClient(app)


def test_api_returns_429_with_retry_after_when_rate_limited() -> None:
    client = _client(_limiter(Clock(), per_minute=1))
    body = {"question": "hola", "history": []}

    assert client.post("/api/ask", json=body).status_code == 200
    blocked = client.post("/api/ask", json=body)

    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"


def test_api_returns_429_when_daily_cap_is_reached() -> None:
    client = _client(_limiter(Clock(), daily_cap=0))

    response = client.post("/api/ask", json={"question": "hola", "history": []})

    assert response.status_code == 429
    assert "diario" in response.json()["detail"]


def test_forwarded_header_identifies_the_client_behind_the_proxy() -> None:
    client = _client(_limiter(Clock(), per_minute=1))
    body = {"question": "hola", "history": []}

    first = client.post("/api/ask", json=body, headers={"X-Forwarded-For": "9.9.9.9, 1.1.1.1"})
    other = client.post("/api/ask", json=body, headers={"X-Forwarded-For": "9.9.9.9, 2.2.2.2"})
    same = client.post("/api/ask", json=body, headers={"X-Forwarded-For": "8.8.8.8, 1.1.1.1"})

    assert (first.status_code, other.status_code, same.status_code) == (200, 200, 429)
