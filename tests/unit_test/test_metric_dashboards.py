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
]


@pytest.mark.parametrize("filename", METRIC_FILES)
def test_dashboards_have_distinct_panels_and_environment_scoped_sources(filename: str) -> None:
    dashboard = json.loads((DASHBOARDS / filename).read_text())
    panels = dashboard["panels"]
    assert len({panel["id"] for panel in panels}) == len(panels)
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
                assert "$__timeFilter(" in target["rawSql"]
                assert "SELECT" in target["rawSql"]
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
