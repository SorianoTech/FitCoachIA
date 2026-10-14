"""Execute the actual dashboard SQL on the real current PostgreSQL schema."""

import json
import os
import re
from pathlib import Path

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[2]
DASHBOARDS = ROOT / "infra/observability/config/grafana/provisioning/dashboards/json"
FILES = ["fitcoach-business", "fitcoach-interviews", "fitcoach-agents", "fitcoach-rag"]
SQL_TARGETS = [
    (name, panel["id"], target["rawSql"])
    for name in FILES
    for top in json.loads((DASHBOARDS / f"{name}.json").read_text())["panels"]
    for panel in [top, *top.get("panels", [])]
    for target in panel.get("targets", [])
    if "rawSql" in target
]


def render_sql(sql: str) -> str:
    sql = re.sub(
        r"\$__timeFilter\(([^)]+)\)",
        r"\1 >= TIMESTAMPTZ '2026-01-01' AND \1 <= TIMESTAMPTZ '2027-01-01'",
        sql,
    )
    return sql.replace("${expire_days:raw}", "14").replace(
        "${agent:sqlstring}", "'interviewer','trainer'"
    )


async def connect() -> asyncpg.Connection:
    return await asyncpg.connect(
        os.getenv(
            "IT_DB_URL",
            f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "panel_id", "sql"), SQL_TARGETS)
async def test_every_dashboard_sql_executes(name: str, panel_id: int, sql: str) -> None:
    connection = await connect()
    try:
        await connection.fetch(render_sql(sql))
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_empty_cohort_is_unknown_and_unknown_prices_are_not_free() -> None:
    connection = await connect()
    transaction = connection.transaction()
    await transaction.start()
    try:
        empty_sql = next(
            sql for name, panel_id, sql in SQL_TARGETS if name == FILES[0] and panel_id == 1
        )
        empty_sql = (
            render_sql(empty_sql)
            .replace("2026-01-01", "2100-01-01")
            .replace("2027-01-01", "2101-01-01")
        )
        assert (await connection.fetchrow(empty_sql))["completion_pct"] is None
        await connection.execute(
            """INSERT INTO token_usage(chat_id,agent,model,prompt_tokens,completion_tokens,
               total_tokens,status,latency_ms,cost_usd,created_at)
               VALUES (876543219,'trainer','unknown-test-price',10,5,15,'success',100,NULL,
                       TIMESTAMPTZ '2090-01-02')"""
        )
        costs = next(
            sql
            for name, panel_id, sql in SQL_TARGETS
            if name == "fitcoach-agents" and panel_id == 3
        )
        costs = (
            render_sql(costs)
            .replace("2026-01-01", "2090-01-01")
            .replace("2027-01-01", "2091-01-01")
        )
        row = await connection.fetchrow(costs)
        assert row["calls"] == 1
        assert row["known_cost_usd"] is None
        assert row["price_coverage_pct"] == 0
    finally:
        await transaction.rollback()
        await connection.close()


def business_sql(panel_id: int, start: str, end: str) -> str:
    sql = next(sql for name, pid, sql in SQL_TARGETS if name == FILES[0] and pid == panel_id)
    return render_sql(sql).replace("2026-01-01", start).replace("2027-01-01", end)


@pytest.mark.asyncio
async def test_satisfaction_weights_customers_equally_and_excludes_open_or_cancelled() -> None:
    connection = await connect()
    transaction = connection.transaction()
    await transaction.start()
    try:
        evaluations = [
            (876543301, "answered", 1),
            (876543301, "answered", 2),
            (876543301, "unanswered", None),
            (876543302, "answered", 5),
            (876543302, "awaiting", None),
            (876543303, "awaiting", None),
        ]
        for chat_id, status, score in evaluations:
            await connection.execute(
                """INSERT INTO training_evaluation(chat_id,week_number,answer_status,score,sent_at)
                   VALUES ($1,1,$2,$3,TIMESTAMPTZ '2090-01-02')""",
                chat_id,
                status,
                score,
            )
        jobs = [
            ("evaluation_poll", "done"),
            ("evaluation_poll", "done"),
            ("evaluation_poll", "done"),
            ("evaluation_poll", "failed"),
            ("evaluation_poll", "cancelled"),
            ("training_reminder", "failed"),
        ]
        for index, (job_type, state) in enumerate(jobs):
            await connection.execute(
                """INSERT INTO job_execution(job_type,chat_id,payload,dedup_key,state,
                   execution_date,executed_at) VALUES ($1,876543301,'{}',$2,$3,
                   TIMESTAMPTZ '2090-01-02',TIMESTAMPTZ '2090-01-02')""",
                job_type,
                f"dashboard-test:{index}",
                state,
            )
        satisfaction = await connection.fetchrow(business_sql(8, "2090-01-01", "2091-01-01"))
        assert satisfaction["satisfaction_avg"] == 3.25
        assert satisfaction["answered_polls"] == 3
        unanswered = await connection.fetchrow(business_sql(9, "2090-01-01", "2091-01-01"))
        assert unanswered["unanswered_pct"] == 25
        assert unanswered["closed_polls"] == 4
        not_generated = await connection.fetchrow(business_sql(10, "2090-01-01", "2091-01-01"))
        assert not_generated["not_generated_pct"] == 25
        assert not_generated["attempted_polls"] == 4
        rows = await connection.fetch(business_sql(12, "2090-01-01", "2091-01-01"))
        assert [row["chat_id"] for row in rows] == [876543301, 876543302, 876543303]
        assert rows[2]["satisfaction_avg"] == 0
        assert rows[2]["answered"] == 0
    finally:
        await transaction.rollback()
        await connection.close()


@pytest.mark.asyncio
async def test_satisfaction_panels_show_zero_without_data() -> None:
    connection = await connect()
    try:
        expected = {
            8: ("satisfaction_avg", "answered_polls"),
            9: ("unanswered_pct", "closed_polls"),
            10: ("not_generated_pct", "attempted_polls"),
        }
        for panel_id, (metric, count) in expected.items():
            row = await connection.fetchrow(business_sql(panel_id, "2100-01-01", "2101-01-01"))
            assert row[metric] == 0
            assert row[count] == 0
        assert await connection.fetch(business_sql(12, "2100-01-01", "2101-01-01")) == []
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_versions_do_not_multiply_profiles_and_catalogue_ids_are_unique() -> None:
    from tests.unit_test.conftest import build_plan_payload

    connection = await connect()
    transaction = connection.transaction()
    await transaction.start()
    try:
        for chat_id in (876543217, 876543218):
            await connection.execute(
                """INSERT INTO interviewer_profiles(chat_id,profile,report,completed_at)
                   VALUES ($1,'{}','dashboard-test',TIMESTAMPTZ '2090-01-02')""",
                chat_id,
            )
        for version in (1, 2):
            await connection.execute(
                """INSERT INTO training_plans(chat_id,version,plan,report,change_kind,
                   retrieved_exercise_ids,created_at) VALUES
                   (876543217,$1,$2,'dashboard-test','initial',$3,TIMESTAMPTZ '2090-01-02')""",
                version,
                json.dumps(build_plan_payload()),
                json.dumps([101, 101, 999]) if version == 1 else None,
            )
        profile_sql = next(
            sql for name, panel_id, sql in SQL_TARGETS if name == FILES[0] and panel_id == 2
        )
        profile_sql = (
            render_sql(profile_sql)
            .replace("2026-01-01", "2090-01-01")
            .replace("2027-01-01", "2091-01-01")
        )
        assert (await connection.fetchrow(profile_sql))["profiles_with_plan_pct"] == 50
        catalogue_sql = next(
            sql for name, panel_id, sql in SQL_TARGETS if name == "fitcoach-rag" and panel_id == 5
        )
        catalogue_sql = (
            render_sql(catalogue_sql)
            .replace("2026-01-01", "2090-01-01")
            .replace("2027-01-01", "2091-01-01")
        )
        rows = await connection.fetch(catalogue_sql)
        assert len(rows) == 1
        assert rows[0]["provided_ids"] == 2
        assert rows[0]["used_ids"] == 1
        assert rows[0]["context_utilization_pct"] == 50
        assert rows[0]["used_outside_catalogue"] == 0
    finally:
        await transaction.rollback()
        await connection.close()
