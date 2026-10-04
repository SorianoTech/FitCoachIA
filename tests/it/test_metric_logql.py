"""Optional isolated Loki validation: METRICS_LOKI_URL, never production logs."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

URL = os.getenv("METRICS_LOKI_URL")
RUN_ID = str(uuid4())
pytestmark = pytest.mark.skipif(not URL, reason="Requires isolated METRICS_LOKI_URL")
DASHBOARDS = (
    Path(__file__).resolve().parents[2]
    / "infra/observability/config/grafana/provisioning/dashboards/json"
)
QUERIES = [
    (path.stem, panel["id"], target["expr"])
    for path in sorted(DASHBOARDS.glob("*.json"))
    if path.stem != "fitcoach-conversations"
    for panel in json.loads(path.read_text())["panels"]
    for target in panel.get("targets", [])
    if "expr" in target
]


@pytest.fixture(scope="module")
def loki() -> httpx.Client:
    with httpx.Client(base_url=URL, timeout=30) as client:
        assert client.get("/ready").status_code == 200
        messages = [
            *["telegram_user_id=1 update recibido"] * 4,
            "telegram_user_id=1 update ignorado: no contiene texto",
            *["telegram_user_id=1 comando=Commands.INTERVIEW"] * 2,
            "training_latency action=renewal phase=retrieval result=ok duration_ms=10.000",
            "training_latency action=renewal phase=retrieval result=error duration_ms=20.000",
            "training_latency action=renewal phase=embeddings result=ok duration_ms=5.000",
            "training_latency action=renewal phase=llm result=ok duration_ms=100.000",
            "training_latency action=renewal phase=llm result=ok duration_ms=200.000",
            "RAG ranking group=chest count=8 distance_min=0.2 distance_max=0.6",
            "RAG ranking group=chest count=4 distance_min=0.4 distance_max=0.8",
            "RAG ranking group=chest count=0 distance_min=None distance_max=None",
            "RAG catalogue has no eligible exercise for group=chest",
            "RAG ranking group=back count=2 distance_min=0.5 distance_max=0.7",
        ]
        now = time.time_ns()
        result = client.post(
            "/loki/api/v1/push",
            json={
                "streams": [
                    {
                        "stream": {
                            "service_name": "fitcoach-ia",
                            "environment": "dashboard-test",
                            "validation_run": RUN_ID,
                        },
                        "values": [
                            [
                                str(now - (len(messages) - index) * 1000000000),
                                json.dumps({"message": message}),
                            ]
                            for index, message in enumerate(messages)
                        ],
                    }
                ]
            },
        )
        assert result.status_code == 204
        yield client


def query(loki: httpx.Client, expr: str) -> list[dict]:
    expr = expr.replace(
        'environment="$environment"',
        f'environment="$environment",validation_run="{RUN_ID}"',
    )
    expr = (
        expr
        .replace("$environment", "dashboard-test")
        .replace("$__range", "1h")
        .replace("$__interval", "5m")
    )
    params = {"query": expr}
    endpoint = "/loki/api/v1/query"
    if "| line_format" in expr:
        endpoint = "/loki/api/v1/query_range"
        params.update({"start": str(time.time_ns() - 3600 * 10**9), "end": str(time.time_ns())})
    response = loki.get(endpoint, params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    return body["data"]["result"]


@pytest.mark.parametrize(("name", "panel_id", "expr"), QUERIES)
def test_all_logql_queries_parse(loki: httpx.Client, name: str, panel_id: int, expr: str) -> None:
    query(loki, expr)


@pytest.mark.parametrize(
    ("name", "panel_id", "expected"),
    [("fitcoach-telegram", 1, 25), ("fitcoach-rag", 1, 50), ("fitcoach-interviews", 5, 100)],
)
def test_logql_ratios_count_observed_events(
    loki: httpx.Client, name: str, panel_id: int, expected: int
) -> None:
    expr = next(
        expr for dashboard, panel, expr in QUERIES if dashboard == name and panel == panel_id
    )
    result = query(loki, expr)
    assert len(result) == 1
    assert float(result[0]["value"][1]) == expected


def test_logql_p95_is_grouped_by_phase_not_summed(loki: httpx.Client) -> None:
    expr = [
        expr for dashboard, panel, expr in QUERIES if dashboard == "fitcoach-agents" and panel == 6
    ][1]
    result = query(loki, expr)
    llm = next(item for item in result if item["metric"]["phase"] == "llm")
    assert float(llm["value"][1]) == pytest.approx(195)


@pytest.mark.parametrize(
    ("panel_id", "expected"),
    [
        (8, {"chest": 4, "back": 2}),
        (9, {"chest": 100 / 3, "back": 0}),
        (10, {"chest": 0.3, "back": 0.5}),
    ],
)
def test_rag_rankings_measure_observed_groups(
    loki: httpx.Client, panel_id: int, expected: dict[str, float]
) -> None:
    expr = next(
        expr for name, panel, expr in QUERIES if name == "fitcoach-rag" and panel == panel_id
    )
    result = query(loki, expr)
    assert {item["metric"]["group"] for item in result} == set(expected)
    for item in result:
        assert float(item["value"][1]) == pytest.approx(expected[item["metric"]["group"]])


def test_rag_table_formats_only_rankings(loki: httpx.Client) -> None:
    expr = next(expr for name, panel, expr in QUERIES if name == "fitcoach-rag" and panel == 11)
    result = query(loki, expr)
    rows = [json.loads(line) for stream in result for _, line in stream["values"]]
    assert len(rows) == 4
    assert all(set(row) == {"group", "count", "distance_min", "distance_max"} for row in rows)
    assert next(row for row in rows if row["count"] == "0")["distance_min"] == "None"
