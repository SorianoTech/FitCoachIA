import httpx


class TestHealthEndpointIntegration:
    def test_health_endpoint_responds(self, client: httpx.Client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
