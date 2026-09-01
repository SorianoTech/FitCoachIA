import os
from collections.abc import Iterator

import httpx
import pytest

BASE_URL = os.getenv("IT_BASE_URL", "http://localhost:8001")


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    """Cliente HTTP contra el contenedor levantado por `make it_tests`."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as http_client:
        yield http_client
