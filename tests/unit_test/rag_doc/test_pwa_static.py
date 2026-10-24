import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parents[3] / "infra/rag-doc/rag_doc/static"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return TestClient(app)


@pytest.mark.parametrize(
    "path", ["/", "/app.js", "/styles.css", "/manifest.json", "/sw.js", "/offline.html"]
)
def test_static_asset_is_served(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


def test_unknown_static_path_returns_404(client: TestClient) -> None:
    assert client.get("/nope.js").status_code == 404


def test_manifest_icons_exist_and_are_png() -> None:
    manifest = json.loads((STATIC / "manifest.json").read_text())
    assert manifest["display"] == "standalone"
    assert {i["sizes"] for i in manifest["icons"]} >= {"192x192", "512x512"}
    for icon in manifest["icons"]:
        assert (STATIC / icon["src"].lstrip("/")).read_bytes().startswith(PNG_MAGIC)


def test_service_worker_precaches_existing_files_and_skips_api() -> None:
    sw = (STATIC / "sw.js").read_text()
    shell = re.search(r"APP_SHELL = \[(.*?)\]", sw, re.S)
    assert shell is not None
    for entry in re.findall(r"'/([^']*)'", shell.group(1)):
        assert (STATIC / (entry or "index.html")).exists(), entry
    assert "/api/" in sw
