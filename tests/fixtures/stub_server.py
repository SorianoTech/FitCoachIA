"""Stub de las tres dependencias externas de la app, en un solo proceso.

Telegram, el proveedor LLM y el embedder hablan HTTP y JSON, asi que un unico
servidor con rutas distintas basta y evita levantar tres contenedores. Solo usa
la libreria estandar: la imagen es `python:3.11-slim` sin build ni dependencias.

Rutas:
  POST /bot<token>/getMe|setMyCommands|sendMessage   -> Telegram
  POST /v1/chat/completions                          -> proveedor LLM
  POST /embed                                        -> servicio de embeddings
  GET  /health                                       -> sonda del compose
  GET  /__sent                                       -> mensajes que la app envio
"""

import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9999
EMBEDDING_DIMENSIONS = 384

# Ids que existen en tests/fixtures/exercises_min.sql. El plan del stub solo
# puede usar estos: es justo la invariante que el test comprueba.
FIXTURE_EXERCISE_IDS = (1, 2)

# Mensajes enviados por la app, para que el test pueda inspeccionarlos.
SENT_MESSAGES: list[dict[str, object]] = []

_INTERVIEW_PROFILE = {
    "user": {"name_or_username": "Ana", "registration_date": "2026-01-01T00:00:00Z"},
    "biometrics": {
        "age": 30,
        "weight_kg": 70.0,
        "height_cm": 170,
        "bmi": 24.2,
        "perceived_composition": "algo de grasa",
        "estimated_composition": "normal",
    },
    "goal": {
        "primary": "gain_muscle",
        "secondary": None,
        "timeframe_weeks": 12,
        "realistic_expectation": True,
    },
    "activity": {
        "occupation": "oficina",
        "neat_level": "sedentary",
        "description": "ocho horas sentada",
    },
    "nutrition": {"meals_per_day": 3, "critical_foods": [], "general_pattern": "variada"},
    "digestive_energy": {"bloating_frequency": "never", "energy_crash": False, "triggers": []},
    "injuries": [],
    "training": {"consistent_years": 1.0, "environment": "gym", "equipment": ["barbell"]},
    "sleep": {"average_hours": 7.0, "quality": "good", "problems": []},
    "supplementation": {"current": [], "monthly_budget_usd": None, "restrictions": []},
    # Un solo dia por semana mantiene el plan del stub pequeno y legible.
    "commitment": {
        "days_per_week": 1,
        "minutes_per_session": 60,
        "flexibility": "flexible",
        "dropout_history": None,
    },
    "flags": {"red": [], "yellow": []},
    "initial_calculations": {
        "bmr": 1450.0,
        "estimated_tdee": 2000.0,
        "tolerable_volume_sets": 12,
    },
}

_INTERVIEWER_TURN = {
    "status": "completed",
    "reply": "Entrevista terminada",
    "report": "Tu perfil esta listo. Envia /train para tu plan.",
    "profile": _INTERVIEW_PROFILE,
}

_INTENSITIES = ("accumulation", "intensification", "peak", "deload")

_TRAINER_TURN = {
    "status": "plan",
    "reply": "Aqui tienes tu plan",
    "report": "Plan de 4 semanas, 1 dia por semana.",
    "plan": {
        "goal": "gain_muscle",
        "days_per_week": 1,
        "environment": "gym",
        "weeks": [
            {
                "week": week,
                "intensity": _INTENSITIES[week - 1],
                "days": [
                    {
                        "day": 1,
                        "focus": "Full body",
                        "estimated_minutes": 55,
                        "exercises": [
                            {
                                "exercise_id": exercise_id,
                                "name": f"fixture exercise {exercise_id}",
                                "sets": 3,
                                "reps": "8-10",
                                "rest_seconds": 120,
                                "rpe": 7.0,
                                "notes": None,
                            }
                            for exercise_id in FIXTURE_EXERCISE_IDS
                        ],
                    }
                ],
            }
            for week in range(1, 5)
        ],
        "excluded_by_injury": [],
        "progression_notes": "Sube 2,5 kg al completar el rango alto.",
    },
}


def _completion(content: dict[str, object]) -> dict[str, object]:
    return {
        "id": "stub-1",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(content)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


class StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return  # Silencia el log por peticion: ensucia la salida de los tests.

    def _respond(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - firma de BaseHTTPRequestHandler
        if self.path == "/health":
            self._respond({"status": "healthy"})
        elif self.path == "/__sent":
            self._respond(SENT_MESSAGES)
        elif self.path == "/__reset":
            SENT_MESSAGES.clear()
            self._respond({"ok": True})
        else:
            self._respond({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - firma de BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b""
        body = self._parse_body(raw_body, self.headers.get("Content-Type", ""))

        if self.path.startswith("/v1/chat/completions"):
            self._respond(_completion(self._turn_for(body)))
            return
        if self.path.startswith("/embed"):
            texts = body.get("texts") or []
            self._respond({
                "model": "stub",
                "dimensions": EMBEDDING_DIMENSIONS,
                # Vector constante: con un corpus de 10 filas y top_k alto, la
                # recuperacion devuelve todas, de forma determinista.
                "vectors": [[0.1] * EMBEDDING_DIMENSIONS for _ in texts],
            })
            return

        telegram = re.match(r"^/bot[^/]+/(\w+)", self.path)
        if telegram:
            self._respond(self._telegram(telegram.group(1), body))
            return

        self._respond({"error": "not found"}, status=404)

    @staticmethod
    def _parse_body(raw_body: bytes, content_type: str) -> dict[str, object]:
        """JSON o formulario: python-telegram-bot envia sendMessage urlencoded."""
        if not raw_body:
            return {}
        if "json" in content_type:
            try:
                parsed = json.loads(raw_body)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        fields = urllib.parse.parse_qs(raw_body.decode("utf-8", errors="replace"))
        return {key: values[0] for key, values in fields.items() if values}

    @staticmethod
    def _turn_for(body: dict[str, object]) -> dict[str, object]:
        """Elige la respuesta segun que agente esta llamando."""
        messages = body.get("messages") or []
        system = ""
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "system":
                system = str(message.get("content", ""))
                break
        # Ojo: el prompt del interviewer tambien menciona "Trainer" al citar a
        # los agentes siguientes. Hay que mirar la linea de ROLE.
        if "You are the Trainer" in system:
            return _TRAINER_TURN
        return _INTERVIEWER_TURN

    @staticmethod
    def _telegram(method: str, body: dict[str, object]) -> dict[str, object]:
        if method == "getMe":
            return {
                "ok": True,
                "result": {
                    "id": 1,
                    "is_bot": True,
                    "first_name": "stub",
                    "username": "stub_bot",
                },
            }
        if method == "sendMessage":
            SENT_MESSAGES.append(body)
            return {
                "ok": True,
                "result": {
                    "message_id": len(SENT_MESSAGES),
                    "date": 0,
                    "chat": {"id": body.get("chat_id", 1), "type": "private"},
                    "text": body.get("text", ""),
                },
            }
        return {"ok": True, "result": True}


if __name__ == "__main__":
    # Escucha en todas las interfaces a proposito: es un contenedor de test aislado.
    ThreadingHTTPServer(("0.0.0.0", PORT), StubHandler).serve_forever()  # noqa: S104  # nosec B104
