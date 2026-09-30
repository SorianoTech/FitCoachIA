"""Mock minimo de la API de Telegram para los tests de integracion.

La app falla al arrancar si no consigue registrar el webhook (ver `_register_webhook`
en `main.py`), asi que el contenedor de test necesita algo que responda como Telegram.
Solo stdlib: se monta como volumen sobre una imagen de Python, sin build ni dependencias.

PTB construye las URLs como `<base_url><token>/<metodo>`, de ahi que solo se mire el
ultimo segmento de la ruta.
"""

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import unquote_plus

_PORT = 9999
_URL_PATTERN = re.compile(r"https?://[^\s\"'&\\]+")

# `getWebhookInfo` tiene que devolver la misma URL que acaba de registrar `setWebhook`,
# porque la app compara ambas y aborta si no coinciden.
_registered_webhook_url = ""


class TelegramMockHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802  (firma impuesta por BaseHTTPRequestHandler)
        self._respond()

    def do_POST(self) -> None:  # noqa: N802
        self._respond()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silencia el log por peticion: ensucia la salida de los tests."""

    def _respond(self) -> None:
        method = self.path.rstrip("/").rsplit("/", 1)[-1]
        payload = json.dumps({"ok": True, "result": self._result_for(method)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _result_for(self, method: str) -> object:
        global _registered_webhook_url
        if method == "getMe":
            return {"id": 1, "is_bot": True, "first_name": "Test Bot", "username": "test_bot"}
        if method == "setWebhook":
            match = _URL_PATTERN.search(self._read_body())
            _registered_webhook_url = match.group() if match else ""
            return True
        if method == "getWebhookInfo":
            return {
                "url": _registered_webhook_url,
                "has_custom_certificate": False,
                "pending_update_count": 0,
            }
        return True

    def _read_body(self) -> str:
        """Cuerpo decodificado. PTB puede mandar JSON, multipart o form url-encoded,
        asi que se desescapa y se busca la URL con una expresion regular en vez de
        intentar parsear los tres formatos."""
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return unquote_plus(raw.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    HTTPServer(("", _PORT), TelegramMockHandler).serve_forever()
