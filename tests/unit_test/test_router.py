from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fitcoach.api.router import get_word_counter_service, router
from fitcoach.service.word_counter_service import (
    EmptyMessageError,
    MessageTooLongError,
    WordCounterService,
)


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=WordCounterService)


@pytest.fixture
def client(mock_service: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_word_counter_service] = lambda: mock_service
    return TestClient(app)


class TestTestRouter:
    def test_returns_200_with_most_repeated_word(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.most_repeated_word.return_value = "hello"

        response = client.post("/test", json={"message": "hello world hello"})

        assert response.status_code == 200
        assert response.json() == {
            "message": "hello world hello",
            "most_repeated_word": "hello",
        }
        mock_service.most_repeated_word.assert_called_once_with("hello world hello")

    def test_returns_400_when_service_raises_empty_message_error(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.most_repeated_word.side_effect = EmptyMessageError("Message must not be empty")

        response = client.post("/test", json={"message": ""})

        assert response.status_code == 400
        assert response.json() == {"detail": "Message must not be empty"}

    def test_returns_400_when_message_is_null(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.most_repeated_word.side_effect = EmptyMessageError("Message must not be empty")

        response = client.post("/test", json={"message": None})

        assert response.status_code == 400
        assert response.json() == {"detail": "Message must not be empty"}

    def test_returns_400_when_service_raises_message_too_long(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.most_repeated_word.side_effect = MessageTooLongError(
            "Message length 251 exceeds the maximum of 250"
        )

        response = client.post("/test", json={"message": "a" * 251})

        assert response.status_code == 400
        assert response.json() == {"detail": "Message length 251 exceeds the maximum of 250"}

    def test_returns_422_when_body_is_not_json(self, client: TestClient) -> None:
        response = client.post(
            "/test",
            content="not-a-json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
