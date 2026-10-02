import os
from collections.abc import Iterator

import httpx
import pytest

BASE_URL = os.getenv("IT_BASE_URL", "http://localhost:8001")
# Mismo valor que `bot_telegram_secret_token` en tests/docker-compose-test.yml.
WEBHOOK_SECRET = os.getenv("IT_WEBHOOK_SECRET", "test-secret-token")


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    """Cliente HTTP contra el contenedor levantado por `make it_tests`."""
    headers = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=10.0) as http_client:
        yield http_client
