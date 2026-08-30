from fastapi.testclient import TestClient

from fitcoach.main import app


class TestAppEndpoints:
    def test_root_returns_service_metadata(self) -> None:
        response = TestClient(app).get("/")
        assert response.status_code == 200
        assert response.json()["status"] == "online"

    def test_health_returns_healthy(self) -> None:
        response = TestClient(app).get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
