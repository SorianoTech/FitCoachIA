import httpx


class TestHealthEndpointIntegration:
    def test_health_endpoint_responds(self, client: httpx.Client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_readiness_endpoint_checks_database_dependencies(self, client: httpx.Client) -> None:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
