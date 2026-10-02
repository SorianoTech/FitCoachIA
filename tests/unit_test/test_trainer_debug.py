import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from fitcoach.devtools import trainer_debug
from fitcoach.devtools.recording_model import RecordingChatModel
from fitcoach.devtools.trainer_runner import (
    TrainerVariant,
    artifact_dir,
    dump_catalogue,
    load_catalogue,
    render_messages,
    run_trainer_case,
    write_artifacts,
)
from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.infrastructure.config.settings import IASettings
from tests.unit_test.conftest import build_plan_payload


def _plan_json(exercise_id: int = 101) -> str:
    return json.dumps({
        "status": "plan",
        "reply": "Aquí tienes tu plan",
        "report": "Plan de 4 semanas",
        "plan": build_plan_payload(exercise_id=exercise_id),
    })


@pytest.fixture
def model() -> MagicMock:
    model = MagicMock()
    model.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=_plan_json(),
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
    )
    return model


@pytest.fixture
def profile_file(tmp_path: Path, profile: InterviewerProfile) -> Path:
    path = tmp_path / "ana.json"
    path.write_text(profile.model_dump_json(), encoding="utf-8")
    return path


@pytest.fixture
def catalogue_file(tmp_path: Path, exercises: list[Exercise]) -> Path:
    path = tmp_path / "catalogue.json"
    dump_catalogue(exercises, path)
    return path


class TestRecordingChatModel:
    @pytest.mark.asyncio
    async def test_records_the_error_and_reraises(self) -> None:
        inner = MagicMock()
        inner.ainvoke = AsyncMock(side_effect=TimeoutError("slow"))
        recorder = RecordingChatModel(inner)

        with pytest.raises(TimeoutError):
            await recorder.ainvoke([])

        assert recorder.calls[0].error == "TimeoutError: slow"


class TestRunTrainerCase:
    @pytest.mark.asyncio
    async def test_records_calls_tokens_and_the_plan(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        run = await run_trainer_case("ana", profile, exercises, model, "m", TrainerVariant())

        assert run.status == "plan"
        assert not run.repaired
        assert run.total_tokens == 15
        assert len(run.prompt_fingerprint) == 12
        assert run.calls[0].messages[0]["role"] == "system"
        assert "id: 101" in run.calls[0].messages[0]["content"]

    @pytest.mark.asyncio
    async def test_keeps_both_calls_when_a_repair_happens(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.side_effect = [
            AIMessage(content=_plan_json(exercise_id=999)),
            AIMessage(content=_plan_json(exercise_id=102)),
        ]

        run = await run_trainer_case("ana", profile, exercises, model, "m", TrainerVariant())

        assert run.repaired
        assert run.calls[0].response is not None
        assert '"exercise_id": 999' in run.calls[0].response

    @pytest.mark.asyncio
    async def test_reports_an_agent_error_instead_of_raising(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.return_value = AIMessage(content="nope")

        run = await run_trainer_case("ana", profile, exercises, model, "m", TrainerVariant())

        assert run.status == "error"
        assert run.error == "llm_invalid_output"

    @pytest.mark.asyncio
    async def test_uses_prompt_and_skill_from_custom_roots(
        self, tmp_path: Path, model: MagicMock, profile: InterviewerProfile
    ) -> None:
        (tmp_path / "prompts" / "trainer").mkdir(parents=True)
        (tmp_path / "prompts" / "trainer" / "system_prompt.txt").write_text(
            "CUSTOM <skill>{{skill_content}}</skill> <rag>{{rag_context}}</rag>"
        )
        (tmp_path / "skills" / "exp").mkdir(parents=True)
        (tmp_path / "skills" / "exp" / "SKILL.md").write_text("EXPERIMENTAL SKILL")
        variant = TrainerVariant("exp", "exp", tmp_path / "prompts", tmp_path / "skills")

        run = await run_trainer_case("ana", profile, [], model, "m", variant)

        system_prompt = run.calls[0].messages[0]["content"]
        assert system_prompt.startswith("CUSTOM <skill>EXPERIMENTAL SKILL</skill>")


class TestArtifacts:
    @pytest.mark.asyncio
    async def test_writes_every_artifact(
        self,
        tmp_path: Path,
        model: MagicMock,
        profile: InterviewerProfile,
        exercises: list[Exercise],
    ) -> None:
        run = await run_trainer_case("ana", profile, exercises, model, "m", TrainerVariant())

        out = write_artifacts(run, tmp_path / "run")

        names = {path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()}
        assert {
            "system_prompt.txt",
            "calls/01_request.json",
            "calls/01_response.txt",
            "plan.json",
            "plan.md",
            "profile.json",
            "catalogue.json",
            "run.json",
            "evaluation.json",
            "evaluation.md",
        } <= names
        summary = json.loads((out / "run.json").read_text())
        assert summary["status"] == "plan"
        assert summary["total_tokens"] == 15
        # The fixture plan repeats week 1 in the deload: an explicit skill violation.
        assert summary["eval_errors"] >= 1
        assert summary["score"] == json.loads((out / "evaluation.json").read_text())["score"]
        assert "`deload_volume` [W4]" in (out / "evaluation.md").read_text()
        assert "### Week 4 (deload)" in (out / "plan.md").read_text()
        assert load_catalogue(out / "catalogue.json") == exercises

    @pytest.mark.asyncio
    async def test_writes_the_error_when_the_call_failed(
        self,
        tmp_path: Path,
        model: MagicMock,
        profile: InterviewerProfile,
        exercises: list[Exercise],
    ) -> None:
        model.ainvoke.side_effect = TimeoutError("slow")

        run = await run_trainer_case("ana", profile, exercises, model, "m", TrainerVariant())
        out = write_artifacts(run, tmp_path / "run")

        assert "<error> TimeoutError" in (out / "calls" / "01_response.txt").read_text()
        assert not (out / "plan.json").exists()
        assert not (out / "evaluation.json").exists()
        assert json.loads((out / "run.json").read_text())["score"] is None

    def test_artifact_dir_is_timestamped_and_safe(self, tmp_path: Path) -> None:
        path = artifact_dir(tmp_path, "my case/1", "v 2")

        assert path.parent == tmp_path
        assert path.name.endswith("-my_case_1-v_2")


def test_render_messages_does_not_call_the_model(
    profile: InterviewerProfile, exercises: list[Exercise]
) -> None:
    messages = render_messages(profile, exercises, TrainerVariant())

    assert [message["role"] for message in messages] == ["system", "human"]
    assert "id: 102" in messages[0]["content"]


class TestCli:
    def test_case_dir_provides_profile_and_catalogue(
        self, tmp_path: Path, profile_file: Path, catalogue_file: Path
    ) -> None:
        case = tmp_path / "case_x"
        case.mkdir()
        (case / "profile.json").write_text(profile_file.read_text())
        (case / "catalogue.json").write_text(catalogue_file.read_text())

        code = trainer_debug.main([
            "--case-dir",
            str(case),
            "--out",
            str(tmp_path / "runs"),
            "--render-only",
        ])

        assert code == 0
        [run_dir] = (tmp_path / "runs").iterdir()
        assert "-case_x-default" in run_dir.name

    @pytest.mark.parametrize(
        ("argv", "message"),
        [
            ([], "a profile is required"),
            (["--profile", "PROFILE"], "a catalogue is required"),
        ],
    )
    def test_requires_a_profile_and_a_catalogue(
        self, profile_file: Path, argv: list[str], message: str
    ) -> None:
        argv = [str(profile_file) if arg == "PROFILE" else arg for arg in argv]

        with pytest.raises(SystemExit, match=message):
            trainer_debug.main([*argv, "--render-only"])

    def test_live_retrieval_uses_top_k_and_can_freeze_the_catalogue(
        self,
        tmp_path: Path,
        profile_file: Path,
        exercises: list[Exercise],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[int] = []

        async def fake_retrieve(profile: InterviewerProfile, top_k: int) -> list[Exercise]:
            calls.append(top_k)
            return exercises

        monkeypatch.setattr(trainer_debug, "retrieve_live", fake_retrieve)

        code = trainer_debug.main([
            "--profile",
            str(profile_file),
            "--live-retrieval",
            "--top-k",
            "3",
            "--save-catalogue",
            str(tmp_path / "frozen.json"),
            "--out",
            str(tmp_path / "runs"),
            "--render-only",
        ])

        assert code == 0
        assert calls == [3]
        assert load_catalogue(tmp_path / "frozen.json") == exercises

    def test_render_only_needs_no_llm_settings(
        self, tmp_path: Path, profile_file: Path, catalogue_file: Path
    ) -> None:
        code = trainer_debug.main([
            "--profile",
            str(profile_file),
            "--catalogue",
            str(catalogue_file),
            "--out",
            str(tmp_path / "runs"),
            "--render-only",
        ])

        assert code == 0
        [run_dir] = (tmp_path / "runs").iterdir()
        assert "id: 101" in (run_dir / "system_prompt.txt").read_text()
        assert (run_dir / "messages.json").exists()

    def test_full_run_writes_artifacts_and_returns_zero_for_a_plan(
        self,
        tmp_path: Path,
        profile_file: Path,
        catalogue_file: Path,
        model: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings = IASettings(
            base_url="http://llm",
            token="t",  # noqa: S106
            model="base-model",
            temperature=0.2,
            _env_file=None,  # type: ignore[call-arg]
        )
        monkeypatch.setattr(trainer_debug, "get_ia_settings", lambda: settings)
        built: list[IASettings] = []

        def fake_build(used: IASettings) -> MagicMock:
            built.append(used)
            return model

        monkeypatch.setattr(trainer_debug, "build_trainer_model", fake_build)

        code = trainer_debug.main([
            "--profile",
            str(profile_file),
            "--catalogue",
            str(catalogue_file),
            "--out",
            str(tmp_path / "runs"),
            "--model",
            "other-model",
            "--temperature",
            "0.7",
            "--max-tokens",
            "9000",
            "--save-catalogue",
            str(tmp_path / "saved.json"),
        ])

        assert code == 0
        assert built[0].model == "other-model"
        assert built[0].temperature == 0.7
        assert built[0].trainer_max_tokens == 9000
        assert (tmp_path / "saved.json").exists()
        [run_dir] = (tmp_path / "runs").iterdir()
        assert json.loads((run_dir / "run.json").read_text())["model"] == "other-model"

    @pytest.mark.asyncio
    async def test_evaluate_run_rescores_a_stored_run_without_the_llm(
        self,
        tmp_path: Path,
        model: MagicMock,
        profile: InterviewerProfile,
        exercises: list[Exercise],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run = await run_trainer_case("ana", profile, exercises, model, "m", TrainerVariant())
        out = write_artifacts(run, tmp_path / "run")
        (out / "evaluation.md").unlink()

        code = await trainer_debug.main_async(
            trainer_debug.build_parser().parse_args(["--evaluate-run", str(out)])
        )

        assert code == 1
        assert (out / "evaluation.md").exists()
        printed = capsys.readouterr().out
        assert "ERROR   deload_volume [W4]" in printed
        assert "catalogue_missing_group" not in printed
