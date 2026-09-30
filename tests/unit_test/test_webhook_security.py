from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fitcoach.api.security import verify_telegram_secret
from fitcoach.infrastructure.config.settings import Settings, get_settings

SECRT = "secreto-de-prueba_123"  # noqa: S105
HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _client() -> TestClient:
    """App minima: probar la dependencia sin arrastrar el lifespan de `main`."""
    app = FastAPI()

    @app.post("/hook", dependencies=[Depends(verify_telegram_secret)])
    async def hook() -> dict[str, bool]:
        return {"ok": True}

    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="test",
        bot_telegram_token="test-token",  # noqa: S106
        bot_telegram_url="http://test-telegram:9999",
        bot_telegram_commands=["start:Inicia FitCoach"],
        bot_telegram_secret_token=SECRT,  # noqa: S106
        bot_telegram_webhook_base_url="https://example.com",
    )
    return TestClient(app)


class TestRejectedRequests:
    def test_without_the_header_returns_403(self) -> None:
        response = _client().post("/hook")

        assert response.status_code == 403

    def test_with_an_empty_header_returns_403(self) -> None:
        response = _client().post("/hook", headers={HEADER: ""})

        assert response.status_code == 403

    def test_with_a_wrong_secret_returns_403(self) -> None:
        response = _client().post("/hook", headers={HEADER: "otro-secreto"})

        assert response.status_code == 403

    def test_with_a_prefix_of_the_secret_returns_403(self) -> None:
        response = _client().post("/hook", headers={HEADER: SECRT[:-1]})

        assert response.status_code == 403

    def test_a_non_ascii_header_returns_403_and_not_500(self) -> None:
        """Regresion: compare_digest sobre `str` lanzaria TypeError -> 500.

        Va como bytes porque httpx rechaza un `str` no ASCII antes de enviarlo; en el
        cable las cabeceras son bytes y Starlette las decodifica como latin-1, asi que
        un cliente crudo si puede colar estos caracteres.
        """
        response = _client().post("/hook", headers={HEADER.encode(): b"se\xf1uelo"})

        assert response.status_code == 403


class TestAcceptedRequests:
    def test_with_the_right_secret_returns_200(self) -> None:
        response = _client().post("/hook", headers={HEADER: SECRT})

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_the_header_name_is_case_insensitive(self) -> None:
        """Telegram no garantiza el casing; HTTP dice que da igual."""
        response = _client().post("/hook", headers={HEADER.lower(): SECRT})

        assert response.status_code == 200
