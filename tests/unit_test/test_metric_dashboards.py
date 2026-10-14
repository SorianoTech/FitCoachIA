"""Provisioned metrics must keep environment and measurement semantics explicit."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DASHBOARDS = ROOT / "infra/observability/config/grafana/provisioning/dashboards/json"
METRIC_FILES = [
    "fitcoach-business.json",
    "fitcoach-interviews.json",
    "fitcoach-telegram.json",
    "fitcoach-agents.json",
    "fitcoach-rag.json",
    "fitcoach-exercise-moderation.json",
]


def flatten(panels: list[dict]) -> list[dict]:
    """Panels with those nested in collapsed rows; rows themselves are left out."""
    flat: list[dict] = []
    for panel in panels:
        if panel["type"] == "row":
            flat.extend(panel.get("panels", []))
        else:
            flat.append(panel)
    return flat


@pytest.mark.parametrize("filename", METRIC_FILES)
def test_dashboards_have_distinct_panels_and_environment_scoped_sources(filename: str) -> None:
    dashboard = json.loads((DASHBOARDS / filename).read_text())
    ids = [panel["id"] for panel in dashboard["panels"]] + [
        nested["id"] for panel in dashboard["panels"] for nested in panel.get("panels", [])
    ]
    assert len(set(ids)) == len(ids)
    panels = flatten(dashboard["panels"])
    environment = next(
        item for item in dashboard["templating"]["list"] if item["name"] == "environment"
    )
    assert environment["query"] == "dev,prod"
    assert not environment["multi"]
    for panel in panels:
        if panel["type"] == "text":
            continue
        assert panel["description"]
        datasource = panel["datasource"]
        for target in panel["targets"]:
            if datasource["type"] == "postgres":
                assert datasource["uid"] == "fitcoach-postgres-${environment}"
                assert "SELECT" in target["rawSql"]
                if "$__timeFilter(" not in target["rawSql"]:
                    assert "status='pending'" in target["rawSql"]
                    assert "actual" in panel["description"].lower()
            else:
                assert 'environment="$environment"' in target["expr"]
                assert datasource["uid"] == "loki"
                assert "traces_spanmetrics" not in target["expr"]


def test_unique_dashboard_uids_include_legacy_dashboard() -> None:
    dashboards = [json.loads(path.read_text()) for path in DASHBOARDS.glob("*.json")]
    assert len({item["uid"] for item in dashboards}) == len(dashboards)
    assert any(item["uid"] == "fitcoach-conversations" for item in dashboards)


def test_cost_and_catalogue_panels_expose_coverage_instead_of_silent_defaults() -> None:
    business = json.loads((DASHBOARDS / METRIC_FILES[0]).read_text())
    costs = next(panel for panel in business["panels"] if panel["id"] == 6)
    assert "price_coverage_pct" in costs["targets"][0]["rawSql"]
    assert "NULLIF" in costs["targets"][0]["rawSql"]
    rag = json.loads((DASHBOARDS / "fitcoach-rag.json").read_text())
    catalogue = next(panel for panel in rag["panels"] if panel["id"] == 5)
    assert "('initial','renewal')" in catalogue["targets"][0]["rawSql"]
    assert "used_outside_catalogue" in catalogue["targets"][0]["rawSql"]


def test_satisfaction_panels_default_to_zero_and_expose_their_denominator() -> None:
    business = json.loads((DASHBOARDS / METRIC_FILES[0]).read_text())
    panels = {panel["id"]: panel for panel in flatten(business["panels"])}
    counts = {8: "answered_polls", 9: "closed_polls", 10: "attempted_polls"}
    for panel_id, count in counts.items():
        sql = panels[panel_id]["targets"][0]["rawSql"]
        assert sql.startswith("SELECT COALESCE(")
        assert f"AS {count}" in sql
        assert panels[panel_id]["options"]["textMode"] == "value_and_name"
    assert "answer_status='answered'" in panels[8]["targets"][0]["rawSql"]
    assert "GROUP BY chat_id" in panels[8]["targets"][0]["rawSql"]
    assert "awaiting" not in panels[9]["targets"][0]["rawSql"]
    not_generated = panels[10]["targets"][0]["rawSql"]
    assert "job_type='evaluation_poll'" in not_generated
    assert "state IN ('done','failed')" in not_generated
    assert "cancelled" not in not_generated
    assert "N4" not in panels[7]["options"]["content"]


def test_customer_detail_is_a_collapsed_row_and_ranks_unanswered_last() -> None:
    business = json.loads((DASHBOARDS / METRIC_FILES[0]).read_text())
    row = next(panel for panel in business["panels"] if panel["id"] == 11)
    assert row["type"] == "row"
    assert row["collapsed"] is True
    assert [nested["id"] for nested in row["panels"]] == [12]
    assert all(panel["id"] != 12 for panel in business["panels"])
    sql = row["panels"][0]["targets"][0]["rawSql"]
    assert "ORDER BY count(*) FILTER (WHERE answer_status='answered')=0" in sql


def test_rag_rankings_do_not_present_similarity_as_quality() -> None:
    dashboard = json.loads((DASHBOARDS / "fitcoach-rag.json").read_text())
    panels = {panel["id"]: panel for panel in dashboard["panels"]}
    for panel_id in (8, 9, 10, 11):
        assert "RAG ranking " in panels[panel_id]["targets"][0]["expr"]
    assert 'count="0"' in panels[9]["targets"][0]["expr"]
    assert "or on (group)" in panels[9]["targets"][0]["expr"]
    assert "WARNING" not in panels[9]["targets"][0]["expr"]
    assert 'count!="0"' in panels[10]["targets"][0]["expr"]
    assert "no mejor calidad" in panels[10]["description"]
    assert "thresholds" not in panels[10]["fieldConfig"]["defaults"]
    assert panels[11]["targets"][0]["maxLines"] == 100


def test_exercise_moderation_dashboard_exposes_backlog_without_personal_data() -> None:
    dashboard = json.loads((DASHBOARDS / "fitcoach-exercise-moderation.json").read_text())
    panels = {panel["id"]: panel for panel in dashboard["panels"]}
    queue_sql = panels[4]["targets"][0]["rawSql"]
    assert "status='pending'" in queue_sql
    assert "ORDER BY created_at,id LIMIT 100" in queue_sql
    assert "chat_id" not in queue_sql
    assert "raw_description" not in queue_sql
    assert "ai_validity" in queue_sql
    assert "duplicate_exercise_id" in queue_sql
    for panel_id in (1, 2, 3, 4, 5):
        assert "$__timeFilter(" not in panels[panel_id]["targets"][0]["rawSql"]
    for panel_id in (6, 7, 8):
        assert "$__timeFilter(reviewed_at)" in panels[panel_id]["targets"][0]["rawSql"]
    assert "/approve_exercise ID" in panels[9]["options"]["content"]
    assert "/reject_exercise ID MOTIVO" in panels[9]["options"]["content"]
