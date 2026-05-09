import pytest
from fastapi.testclient import TestClient

from fitcoach.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


class TestTestEndpointIntegration:
    def test_happy_path_returns_most_repeated_word(self, client: TestClient) -> None:
        message = "fitcoach is great fitcoach helps fitcoach"

        response = client.post("/test", json={"message": message})

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == message
        assert body["most_repeated_word"] == "fitcoach"

    def test_case_insensitive_and_punctuation(self, client: TestClient) -> None:
        message = "Hello, hello! HELLO. world?"

        response = client.post("/test", json={"message": message})

        assert response.status_code == 200
        assert response.json()["most_repeated_word"] == "hello"

    def test_returns_400_when_message_is_empty_string(self, client: TestClient) -> None:
        response = client.post("/test", json={"message": ""})

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_returns_400_when_message_is_null(self, client: TestClient) -> None:
        response = client.post("/test", json={"message": None})

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_returns_400_when_message_is_only_whitespace(self, client: TestClient) -> None:
        response = client.post("/test", json={"message": "     "})

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_returns_400_when_message_exceeds_max_length(self, client: TestClient) -> None:
        response = client.post("/test", json={"message": "a" * 251})

        assert response.status_code == 400
        assert "exceeds" in response.json()["detail"].lower()

    def test_accepts_message_with_exactly_max_length(self, client: TestClient) -> None:
        message = "word " * 50
        assert len(message) == 250

        response = client.post("/test", json={"message": message})

        assert response.status_code == 200
        assert response.json()["most_repeated_word"] == "word"
