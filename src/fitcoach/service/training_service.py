"""Training mutations require a persisted proposal and an explicit confirmation."""

import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from telegram import InlineKeyboardMarkup
from telegram.error import RetryAfter

from fitcoach.domain.agent_errors import AgentError
from fitcoach.domain.constants import Constants
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.domain.trainer_plan import PlannedExercise, SwapSelection, TrainerTurn, TrainingPlan
from fitcoach.domain.training_lifecycle import (
    SwapReasonSource,
    SwapRequest,
    TrainingAdaptationContext,
    TrainingReview,
    TrainingWorkflow,
    apply_swap,
    prescribed_summary,
    utc_now,
)
from fitcoach.infrastructure.observability.latency import latency_action, latency_phase, timed
from fitcoach.repository.conversation_repository import ConversationRepository
from fitcoach.repository.training_repository import TrainingConflictError, TrainingRepository
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever, available_equipment
from fitcoach.service.agent.plan_evaluator import Severity, estimate_session_minutes, evaluate_turn
from fitcoach.service.agent.trainer_chain import TrainerChain
from fitcoach.service.agent.training_adaptation_chain import TrainingAdaptationChain
from fitcoach.service.training_controls import training_keyboard
from fitcoach.service.training_preview import details, preview
from fitcoach.service.training_view import view_keyboard, view_plan

logger = logging.getLogger(__name__)


class TrainingInputError(ValueError):
    """A user action needs clarification; its message is safe to show."""


class TrainingService:
    def __init__(
        self,
        repository: TrainingRepository,
        conversation: ConversationRepository,
        trainer: TrainerChain,
        retriever: ExerciseRetriever,
        adaptation: TrainingAdaptationChain,
        limits: UsageLimits,
        clock: Callable[[], datetime] = utc_now,
        reminder_max_attempts: int = 5,
        miniapp_url: str | None = None,
        performance_summary: Callable[[int, int], Awaitable[dict[str, object]]] | None = None,
    ) -> None:
        self._repository = repository
        self._conversation = conversation
        self._trainer = trainer
        self._retriever = retriever
        self._adaptation = adaptation
        self._limits = limits
        self._clock = clock
        self._reminder_max_attempts = reminder_max_attempts
        self._miniapp_url = miniapp_url
        self._performance_summary = performance_summary

    async def profile(self, chat_id: int) -> InterviewerProfile | None:
        return await self._repository.effective_profile(
            chat_id
        ) or await self._conversation.get_interviewer_profile(chat_id)

    async def has_workflow(self, chat_id: int) -> bool:
        return await self._repository.get_workflow(chat_id) is not None

    async def keyboard(self, chat_id: int, responses: list[str]) -> InlineKeyboardMarkup | None:
        if responses and responses[0].startswith((
            Constants.TRAINING_NAVIGATION["title"].split("{")[0],
            Constants.TRAINING_NAVIGATION["week_title"],
        )):
            stored = await self._conversation.get_current_plan(chat_id)
            pending = await self._repository.get_workflow(chat_id)
            return (
                view_keyboard(stored.id, pending=pending is not None, miniapp_url=self._miniapp_url)
                if stored
                else None
            )
        workflow = await self._repository.get_workflow(chat_id)
        if workflow is None:
            return None
        plan = workflow.base_draft
        if workflow.answers.get("swap_step") and plan is None:
            stored = await self._conversation.get_current_plan(chat_id)
            plan = stored.plan if stored else None
        return training_keyboard(workflow, responses, plan)

    async def callback(self, chat_id: int, data: str) -> list[str]:
        try:
            return await self._callback(chat_id, data)
        except TrainingConflictError:
            logger.warning("Training callback conflict for chat %s", chat_id, exc_info=True)
            return [Constants.TRAINING_CALLBACK_INVALID]
        except TrainingInputError as error:
            logger.warning("Training callback needs clarification for chat %s: %s", chat_id, error)
            return [str(error)]

    async def _callback(self, chat_id: int, data: str) -> list[str]:
        if data.startswith("tv:"):
            return await self._view_callback(chat_id, data)
        parts = data.split(":")
        if len(parts) not in (4, 5) or parts[0] != "tr":
            logger.warning("Invalid training callback for chat %s", chat_id)
            return [Constants.TRAINING_CALLBACK_INVALID]

        try:
            workflow_id, revision = int(parts[2]), int(parts[3])
        except ValueError:
            logger.warning("Invalid callback identifiers for chat %s", chat_id)
            return [Constants.TRAINING_CALLBACK_INVALID]
        workflow = await self._repository.get_workflow(chat_id)
        if workflow is None or workflow.id != workflow_id or workflow.revision != revision:
            logger.warning("Stale training callback for chat %s", chat_id)
            return [Constants.TRAINING_CALLBACK_INVALID]
        action = parts[1]
        value = parts[4] if len(parts) == 5 else ""
        if action in ("exercise", "page", "week", "reason"):
            return await self._swap_button(chat_id, workflow, action, value)
        if (
            action in ("good", "changes")
            and workflow.kind == "renewal"
            and workflow.state == "reviewing"
            and await self._next_question(chat_id, workflow)
            in (Constants.TRAINING_CLOSURE_QUESTION, Constants.TRAINING_REVIEW_CHOICE)
        ):
            return await self._begin_review(chat_id, workflow, quick=action == "good")
        if (
            action == "details"
            and workflow.draft is not None
            and workflow.state == "awaiting_confirmation"
        ):
            return details(workflow)
        if (
            action == "accept"
            and workflow.draft is not None
            and workflow.state == "awaiting_confirmation"
        ):
            await self._repository.accept(
                chat_id, workflow.id, self._clock(), expected_revision=revision
            )
            return [Constants.TRAINING_ACCEPTED_MESSAGE]
        if action == "cancel":
            workflow.state = "cancelled"
            await self._repository.save(chat_id, workflow)
            return [Constants.TRAINING_CANCELLED_MESSAGE]
        if action == "select" and value.isdigit():
            return await self._select(chat_id, workflow, workflow.id, int(value))
        if action == "swap" and workflow.draft is not None:
            if workflow.kind == "exercise_swap":
                workflow.draft = None
                workflow.report = None
                workflow.options = []
                workflow.swap = None
                workflow.state = "reviewing"
                await self._repository.save(chat_id, workflow)
                return await self._swap_question(chat_id, workflow=workflow)
            workflow.base_draft = workflow.draft
            workflow.base_report = workflow.report
            workflow.draft = None
            workflow.answers.pop("date_request", None)
            workflow.state = "reviewing"
            await self._repository.save(chat_id, workflow)
            return await self._swap_question(chat_id, workflow.base_draft, workflow)
        if (
            action == "close"
            and await self._next_question(chat_id, workflow) == Constants.TRAINING_CLOSURE_QUESTION
        ):
            workflow = await self._repository.save(chat_id, workflow)
            await self._repository.close_cycle(
                chat_id, self._clock(), expected_plan_id=workflow.base_plan_id
            )
            workflow.answers["closed"] = "confirmed"
            workflow = await self._repository.save(chat_id, workflow)
            return [await self._next_question(chat_id, workflow)]
        if (
            action == "postpone"
            and await self._next_question(chat_id, workflow) == Constants.TRAINING_CLOSURE_QUESTION
        ):
            workflow.state = "cancelled"
            await self._repository.save(chat_id, workflow)
            until = self._date(str((self._clock() + timedelta(days=7)).date()))
            await self._repository.postpone(chat_id, until, expected_plan_id=workflow.base_plan_id)
            return await self.status(chat_id)
        if (
            workflow.state == "awaiting_confirmation"
            and workflow.draft is not None
            and workflow.kind == "renewal"
        ):
            if action == "dates" or (action == "date" and value == "other"):
                workflow.answers["date_request"] = "choose" if action == "dates" else "input"
                try:
                    await self._repository.save(chat_id, workflow)
                except TrainingConflictError:
                    return [Constants.TRAINING_CALLBACK_INVALID]
                return [
                    Constants.TRAINING_DATE_PICKER
                    if action == "dates"
                    else Constants.TRAINING_DATE_INPUT
                ]
            if action == "date" and value in ("tomorrow", "monday"):
                days = 1 if value == "tomorrow" else (7 - self._clock().weekday())
                date = (self._clock() + timedelta(days=days)).date()
                await self._repository.accept(
                    chat_id, workflow.id, self._date(str(date)), expected_revision=revision
                )
                return [Constants.TRAINING_ACCEPTED_MESSAGE]
        logger.warning("Unsupported training callback action for chat %s", chat_id)
        return [Constants.TRAINING_CALLBACK_INVALID]

    async def view(self, chat_id: int, *, mode: str = "home", week: int | None = None) -> list[str]:
        stored = await self._conversation.get_current_plan(chat_id)
        if stored is None:
            return [Constants.NO_PLAN_MESSAGE]
        cycle = await self._repository.get_cycle(chat_id)
        return view_plan(stored, cycle, self._clock(), mode=mode, week=week)

    async def _view_callback(self, chat_id: int, data: str) -> list[str]:
        parts = data.split(":")
        stored = await self._conversation.get_current_plan(chat_id)
        if (
            len(parts) not in (3, 4)
            or not parts[1].isdigit()
            or stored is None
            or int(parts[1]) != stored.id
        ):
            logger.warning("Invalid or stale training view callback for chat %s", chat_id)
            return [Constants.TRAINING_CALLBACK_INVALID]
        action = parts[2]
        if len(parts) == 3 and action == "notes":
            return [
                Constants.TRAINING_NAVIGATION["week_title"]
                + "\n\n"
                + Constants.TRAINING_PREVIEW["progression_notes"]
                + "\n"
                + stored.plan.progression_notes
            ]
        if len(parts) == 3 and action == "resume":
            workflow = await self._repository.get_workflow(chat_id)
            if workflow is None:
                return [Constants.TRAINING_CALLBACK_INVALID]
            return await self._handle(
                chat_id,
                "/train cambiar" if workflow.kind == "exercise_swap" else "/train revisar",
            )
        if len(parts) == 3 and action in ("current", "home"):
            return await self.view(chat_id, mode="week" if action == "current" else "home")
        if len(parts) == 4 and action == "week" and parts[3] in ("1", "2", "3", "4"):
            return await self.view(chat_id, mode="week", week=int(parts[3]))
        if len(parts) == 3 and action in ("swap", "review"):
            return await self._handle(
                chat_id, "/train cambiar" if action == "swap" else "/train revisar"
            )
        logger.warning("Unsupported training view callback for chat %s", chat_id)
        return [Constants.TRAINING_CALLBACK_INVALID]

    async def remind_on_interaction(
        self,
        chat_id: int,
        thread_id: int | None,
        send: Callable[[int, int | None, str], Awaitable[None]],
    ) -> None:
        await self._repository.remember_thread(chat_id, thread_id)
        delivery = await self._repository.reserve_interaction_reminder(
            chat_id, thread_id, self._clock()
        )
        if delivery is None:
            return
        if delivery.attempts > self._reminder_max_attempts:
            await self._repository.finish_reminder(delivery, failed=True)
            return
        try:
            await send(chat_id, thread_id, Constants.TRAINING_DUE_MESSAGE)
        except Exception as error:
            logger.exception("Failed to deliver interaction reminder for chat %s", chat_id)
            delay = timedelta(minutes=5)
            if isinstance(error, RetryAfter):
                requested = error.retry_after
                requested_delay = (
                    requested if isinstance(requested, timedelta) else timedelta(seconds=requested)
                )
                delay = max(delay, requested_delay)
            await self._repository.finish_reminder(
                delivery,
                retry_at=self._clock() + delay,
                failed=delivery.attempts >= self._reminder_max_attempts,
            )
            return
        await self._repository.finish_reminder(delivery)

    async def remember_thread(self, chat_id: int, thread_id: int | None) -> None:
        await self._repository.remember_thread(chat_id, thread_id)

    async def status(self, chat_id: int) -> list[str]:
        cycle = await self._repository.get_cycle(chat_id)
        if cycle is None:
            return [Constants.NO_PLAN_MESSAGE]
        if cycle.completed_at:
            return [Constants.TRAINING_MESSAGES["closed"]]
        if cycle.started_at is None:
            return [Constants.TRAINING_LEGACY_MESSAGE]
        if cycle.due(self._clock()):
            return [Constants.TRAINING_DUE_MESSAGE]
        return [
            Constants.TRAINING_MESSAGES["status"].format(
                start=cycle.started_at.date(),
                end=cycle.expected_end_at.date()
                if cycle.expected_end_at
                else Constants.TRAINING_MESSAGES["unknown_date"],
            )
        ]

    async def handle(
        self,
        chat_id: int,
        text: str,
        *,
        swap_message: str | None = None,
        swap_selection: SwapSelection | None = None,
    ) -> list[str]:
        try:
            return await self._handle(
                chat_id, text, swap_message=swap_message, swap_selection=swap_selection
            )
        except TrainingConflictError:
            logger.warning("Training proposal conflict for chat %s", chat_id, exc_info=True)
            return [Constants.TRAINING_CONFLICT_MESSAGE]
        except TrainingInputError as error:
            logger.warning("Training action needs clarification for chat %s: %s", chat_id, error)
            return [str(error)]

    async def _handle(
        self,
        chat_id: int,
        text: str,
        *,
        swap_message: str | None = None,
        swap_selection: SwapSelection | None = None,
    ) -> list[str]:
        tokens = text.split()
        command = tokens[0] if tokens else ""
        arguments = tokens[1:]
        action = arguments[0].lower() if command == "/train" and arguments else ""
        if command == "/train" and action in ("", "ver", "semana"):
            return await self.view(chat_id, mode="week" if action == "semana" else "home")
        if command == "/progress":
            return await self.status(chat_id)
        if action == "cancelar":
            await self._repository.cancel(chat_id)
            return [Constants.TRAINING_CANCELLED_MESSAGE]
        if action == "avisos":
            if len(arguments) != 2 or arguments[1] not in ("on", "off"):
                raise TrainingInputError(Constants.TRAINING_MESSAGES["reminders_usage"])
            await self._repository.set_reminders(chat_id, arguments[1] == "on")
            return [Constants.TRAINING_MESSAGES["reminders_saved"]]
        if action in ("inicio", "posponer"):
            if len(arguments) != 2:
                raise TrainingInputError(Constants.TRAINING_MESSAGES["date_usage"])
            date = self._date(arguments[1])
            if action == "inicio":
                if date > self._clock():
                    raise TrainingInputError(Constants.TRAINING_MESSAGES["start_future"])
                await self._repository.set_start(chat_id, date)
            else:
                if date <= self._clock():
                    raise TrainingInputError(Constants.TRAINING_MESSAGES["postpone_past"])
                await self._repository.postpone(chat_id, date)
                await self._repository.cancel(chat_id)
            return await self.status(chat_id)
        if action == "confirmar":
            if len(arguments) not in (2, 3):
                raise TrainingInputError(Constants.TRAINING_MESSAGES["confirm_usage"])
            start = self._date(arguments[2]) if len(arguments) == 3 else self._clock()
            if start.date() < self._clock().date():
                raise TrainingInputError(Constants.TRAINING_MESSAGES["new_start_past"])
            await self._repository.accept(chat_id, self._integer(arguments[1]), start)
            return [Constants.TRAINING_ACCEPTED_MESSAGE]
        workflow = await self._repository.get_workflow(chat_id)
        if workflow and workflow.answers.get("date_request") == "input" and command != "/train":
            return await self._handle(chat_id, f"/train confirmar {workflow.id} {text.strip()}")
        if action == "editar":
            if (
                workflow is None
                or workflow.kind != "renewal"
                or len(arguments) < 3
                or arguments[1] not in Constants.TRAINING_REVIEW_QUESTIONS
            ):
                raise TrainingInputError(Constants.TRAINING_CONTROLS_MESSAGE)
            workflow.answers[arguments[1]] = " ".join(arguments[2:])
            workflow.answers.pop("quick_review", None)
            workflow.answers.pop("clarification", None)
            workflow.answers.pop("safety_hold", None)
            workflow.review = None
            workflow.effective_profile = None
            workflow.draft = None
            workflow.base_draft = None
            workflow.base_report = None
            workflow.swap = None
            workflow.options = []
            workflow.report = None
            workflow.state = "reviewing"
            workflow.lease_until = None
            workflow = await self._repository.save(chat_id, workflow)
            return [await self._next_question(chat_id, workflow)]
        if action == "elegir":
            if workflow is None or len(arguments) != 3:
                raise TrainingInputError(Constants.TRAINING_MESSAGES["choose_usage"])
            return await self._select(
                chat_id, workflow, self._integer(arguments[1]), self._integer(arguments[2])
            )
        if command == "/train" and action not in ("", "cambiar", "revisar"):
            return [Constants.TRAINING_CONTROLS_MESSAGE]
        if workflow is None:
            workflow = await self._repository.start(
                chat_id, "exercise_swap" if action == "cambiar" else "renewal"
            )
        if swap_message:
            workflow.answers["swap_user_text"] = swap_message
            if swap_selection is None or swap_selection.reason:
                workflow.answers["swap_message"] = swap_message
            if swap_selection and swap_selection.week:
                workflow.answers["swap_week"] = str(swap_selection.week)
                workflow.answers["swap_filter_week"] = str(swap_selection.week)
            if swap_selection and swap_selection.exercise_id:
                workflow.answers["swap_filter_exercise"] = str(swap_selection.exercise_id)
            workflow = await self._repository.save(chat_id, workflow)
        if action == "cambiar" and workflow.kind == "renewal":
            if workflow.draft is None and workflow.base_draft is None:
                raise TrainingInputError(Constants.TRAINING_MESSAGES["pending_review"])
            workflow.base_draft = workflow.draft or workflow.base_draft
            workflow.base_report = workflow.report or workflow.base_report
            workflow.draft = None
            workflow.state = "reviewing"
            workflow.answers.pop("date_request", None)
            workflow = await self._repository.save(chat_id, workflow)
        if workflow.state == "awaiting_confirmation":
            return self._proposal_messages(workflow)
        if workflow.state == "generating":
            if workflow.lease_until and workflow.lease_until > self._clock():
                return [Constants.TRAINING_BUSY_MESSAGE]
            return await self._generate(chat_id, workflow)
        if workflow.kind == "exercise_swap" or workflow.base_draft is not None:
            if workflow.answers.get("safety_hold"):
                return [Constants.TRAINING_SAFETY_MESSAGE]
            if workflow.answers.get("swap_step") == "input" and command != "/train":
                return await self._finish_swap_picker(chat_id, workflow, text)
            if workflow.answers.get("swap_clarification") and workflow.swap:
                if (
                    command == "/train"
                    and action in ("", "cambiar", "revisar")
                    and len(arguments) <= 1
                ):
                    return [workflow.answers["swap_clarification"]]
                if command != "/train":
                    workflow.swap.reason += f"\n{workflow.answers['swap_clarification']}\n{text}"
                    workflow = await self._repository.save(chat_id, workflow)
                    return await self._generate(chat_id, workflow)
            request_text = " ".join(arguments[1:]) if action == "cambiar" else text
            if command == "/train" and (not request_text or action == "revisar"):
                return await self._swap_question(chat_id, workflow.base_draft, workflow)
            return await self._prepare_swap(chat_id, workflow, request_text)
        if command == "/train":
            return [await self._next_question(chat_id, workflow)]
        return await self._review_answer(chat_id, workflow, text)

    @staticmethod
    def _integer(value: str) -> int:
        try:
            result = int(value)
        except ValueError as error:
            raise TrainingInputError(Constants.TRAINING_MESSAGES["invalid_id"]) from error
        if result < 1:
            raise TrainingInputError(Constants.TRAINING_MESSAGES["positive_id"])
        return result

    @staticmethod
    def _date(value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as error:
            raise TrainingInputError(Constants.TRAINING_MESSAGES["invalid_date"]) from error

    async def _next_question(self, chat_id: int, workflow: TrainingWorkflow) -> str:
        cycle = await self._repository.get_cycle(chat_id)
        if "closed" not in workflow.answers and (cycle is None or cycle.completed_at is None):
            return Constants.TRAINING_CLOSURE_QUESTION
        if workflow.answers.get("safety_hold"):
            return Constants.TRAINING_SAFETY_MESSAGE
        if workflow.answers.get("clarification"):
            return workflow.answers["clarification"]
        if workflow.answers.get("review_mode") == "open":
            return Constants.TRAINING_OPEN_REVIEW
        if any(field not in workflow.answers for field in Constants.TRAINING_REVIEW_QUESTIONS):
            return Constants.TRAINING_REVIEW_CHOICE
        return Constants.TRAINING_MESSAGES["review_ready"]

    async def _begin_review(
        self, chat_id: int, workflow: TrainingWorkflow, *, quick: bool
    ) -> list[str]:
        # Persist the revision before closing, so concurrent/stale choices cannot close another plan.
        workflow = await self._repository.save(chat_id, workflow)
        cycle = await self._repository.get_cycle(chat_id)
        if cycle is None or cycle.completed_at is None:
            await self._repository.close_cycle(
                chat_id, self._clock(), expected_plan_id=workflow.base_plan_id
            )
        workflow.answers["closed"] = "confirmed"
        if quick:
            has_previous_feedback = any(
                key in workflow.answers for key in Constants.TRAINING_REVIEW_QUESTIONS
            )
            for key, answer in Constants.TRAINING_QUICK_REVIEW.items():
                workflow.answers.setdefault(key, answer)
            if not has_previous_feedback:
                workflow.answers["quick_review"] = "true"
        else:
            workflow.answers["review_mode"] = "open"
        workflow = await self._repository.save(chat_id, workflow)
        return (
            await self._generate(chat_id, workflow) if quick else [Constants.TRAINING_OPEN_REVIEW]
        )

    async def _review_answer(
        self, chat_id: int, workflow: TrainingWorkflow, text: str
    ) -> list[str]:
        if workflow.answers.get("safety_hold"):
            return [Constants.TRAINING_SAFETY_MESSAGE]
        normalized = text.lower().strip(" .!¡¿?")
        question = await self._next_question(chat_id, workflow)
        if question in (Constants.TRAINING_CLOSURE_QUESTION, Constants.TRAINING_REVIEW_CHOICE):
            if normalized in ("terminé y todo bien", "todo bien", "termine y todo bien"):
                return await self._begin_review(chat_id, workflow, quick=True)
            if normalized in ("quiero ajustar algo", "terminé, pero quiero ajustar algo"):
                return await self._begin_review(chat_id, workflow, quick=False)
            if (
                normalized in ("todavía no", "todavia no")
                and question == Constants.TRAINING_CLOSURE_QUESTION
            ):
                return await self._callback(
                    chat_id, f"tr:postpone:{workflow.id}:{workflow.revision}"
                )
        cycle = await self._repository.get_cycle(chat_id)
        if "closed" not in workflow.answers and (cycle is None or cycle.completed_at is None):
            if text.lower().strip(" .!¡¿?") not in ("sí", "si", "terminado", "he terminado"):
                return [Constants.TRAINING_CLOSURE_QUESTION]
            await self._repository.close_cycle(
                chat_id, self._clock(), expected_plan_id=workflow.base_plan_id
            )
            workflow.answers["closed"] = "confirmed"
            workflow = await self._repository.save(chat_id, workflow)
            return [await self._next_question(chat_id, workflow)]
        if (
            workflow.answers.get("review_mode") == "open"
            or question == Constants.TRAINING_REVIEW_CHOICE
            or workflow.answers.get("clarification")
        ):
            previous = workflow.answers.get("open_review", "")
            clarification = workflow.answers.get("clarification", "")
            workflow.answers["open_review"] = f"{previous}\n{clarification}\n{text}".strip()
            workflow.answers.pop("clarification", None)
            workflow.answers.pop("quick_review", None)
            workflow.answers.pop("review_mode", None)
            for field in Constants.TRAINING_REVIEW_QUESTIONS:
                workflow.answers.setdefault(field, Constants.TRAINING_REVIEW_UNKNOWN)
            workflow = await self._repository.save(chat_id, workflow)
        return await self._generate(chat_id, workflow)

    async def _quota(self, chat_id: int) -> bool:
        used = await self._conversation.tokens_used_since(
            chat_id, self._clock() - self._limits.window
        )
        return used >= self._limits.soft_tokens

    async def _account(self, chat_id: int, usages: list[TokenUsage]) -> None:
        for usage in usages:
            await self._conversation.record_token_usage(
                chat_id=chat_id,
                agent="trainer",
                model=usage.model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                latency_ms=usage.latency_ms,
                status=usage.status,
                conversation_message_id=None,
            )

    async def _generate(self, chat_id: int, workflow: TrainingWorkflow) -> list[str]:
        action = (
            "exercise_swap"
            if workflow.kind == "exercise_swap" or workflow.base_draft is not None
            else "renewal"
        )
        with latency_action(action):
            return await self._generate_workflow(chat_id, workflow)

    @timed("workflow")
    async def _generate_workflow(self, chat_id: int, workflow: TrainingWorkflow) -> list[str]:
        if await self._quota(chat_id):
            return [Constants.QUOTA_SOFT_MESSAGE]
        workflow = await self._repository.claim_generation(chat_id, workflow.id)
        try:
            profile = await self.profile(chat_id)
            stored = await self._conversation.get_current_plan(chat_id)
            if profile is None or stored is None:
                raise TrainingInputError(Constants.NO_PROFILE_MESSAGE)
            if workflow.kind == "exercise_swap" or workflow.base_draft is not None:
                return await self._generate_swap(
                    chat_id,
                    workflow,
                    workflow.effective_profile or profile,
                    workflow.base_draft or stored.plan,
                )
            if workflow.review is None and workflow.answers.get("quick_review"):
                workflow.review = TrainingReview.model_validate({
                    key: workflow.answers[key] for key in Constants.TRAINING_REVIEW_QUESTIONS
                })
                workflow.effective_profile = profile
                workflow = await self._repository.save(chat_id, workflow)
            if workflow.review is None:
                extraction = await self._adaptation.extract_review(profile, workflow.answers)
                await self._account(chat_id, extraction.token_usages)
                review_fields = (
                    extraction.result.summary.model_dump()
                    if extraction.result.summary
                    else {key: workflow.answers[key] for key in Constants.TRAINING_REVIEW_QUESTIONS}
                )
                workflow.review = TrainingReview(
                    **review_fields,
                    user_feedback=workflow.answers.get("open_review", ""),
                    profile_patch=extraction.result.profile_patch,
                    safety_hold=extraction.result.safety_hold,
                )
                workflow.answers["interpretation"] = extraction.result.explanation
                workflow.effective_profile = extraction.result.profile_patch.apply(profile)
                if workflow.review.safety_hold:
                    workflow.answers["safety_hold"] = "true"
                    workflow.state = "reviewing"
                    await self._repository.save(chat_id, workflow)
                    return [Constants.TRAINING_SAFETY_MESSAGE, extraction.result.explanation]
                if extraction.result.clarification:
                    workflow.review = None
                    workflow.effective_profile = None
                    workflow.answers["clarification"] = extraction.result.clarification
                    workflow.state = "reviewing"
                    await self._repository.save(chat_id, workflow)
                    return [extraction.result.clarification]
                workflow = await self._repository.save(chat_id, workflow)
            effective = workflow.effective_profile or profile
            try:
                equipment = available_equipment(effective.training.equipment)
            except ValueError as error:
                logger.warning(
                    "Training equipment needs clarification for chat %s: %s", chat_id, error
                )
                workflow.review = None
                workflow.effective_profile = None
                workflow.answers.pop("quick_review", None)
                workflow.answers["clarification"] = Constants.TRAINING_EQUIPMENT_QUESTION
                workflow.state = "reviewing"
                await self._repository.save(chat_id, workflow)
                return [Constants.TRAINING_EQUIPMENT_QUESTION]
            previous = await self._retriever.get_by_ids(sorted(stored.plan.exercise_ids()))
            candidates = await self._retriever.retrieve(effective)
            catalogue = {
                item.id: item for item in [*previous, *candidates] if item.equipment in equipment
            }
            if not catalogue:
                raise TrainingInputError(Constants.TRAINER_UNAVAILABLE_MESSAGE)
            if workflow.review is None:
                raise TrainingConflictError("Validated review disappeared during generation")
            cycle = await self._repository.get_cycle(chat_id)
            recorded = (
                await self._performance_summary(chat_id, cycle.id)
                if self._performance_summary is not None and cycle is not None
                else {}
            )
            context = TrainingAdaptationContext(
                profile=effective,
                previous_plan=stored.plan,
                previous_version=stored.version,
                review=workflow.review,
                prescribed_summary=prescribed_summary(stored.plan, previous),
                recorded_performance=recorded,
            )
            reply = await self._trainer.generate_next_plan(context, list(catalogue.values()))
            await self._account(chat_id, reply.token_usages)
            if reply.turn.plan is None or reply.turn.report is None:
                raise TrainingInputError(Constants.LLM_INVALID_OUTPUT_ERROR_MESSAGE)
            workflow.draft = reply.turn.plan
            workflow.report = reply.turn.report
            if reply.trace:
                workflow.prompt_trace = asdict(reply.trace)
                workflow.prompt_trace["retrieved_exercise_ids"] = list(
                    reply.trace.retrieved_exercise_ids
                )
                workflow.generation_traces.append(workflow.prompt_trace.copy())
            workflow.state = "awaiting_confirmation"
            workflow = await self._repository.save(chat_id, workflow)
            return self._proposal_messages(workflow)
        except AgentError as error:
            await self._account(chat_id, error.token_usages)
            await self._release(chat_id, workflow)
            raise
        except Exception:
            await self._release(chat_id, workflow)
            raise

    async def _release(self, chat_id: int, workflow: TrainingWorkflow) -> None:
        workflow.state = "reviewing"
        workflow.lease_until = None
        try:
            await self._repository.save(chat_id, workflow)
        except TrainingConflictError:
            logger.warning("Generation lease no longer owned for chat %s", chat_id)

    async def _swap_question(
        self,
        chat_id: int,
        draft: TrainingPlan | None = None,
        workflow: TrainingWorkflow | None = None,
    ) -> list[str]:
        stored = await self._conversation.get_current_plan(chat_id)
        if stored is None and draft is None:
            return [Constants.NO_PLAN_MESSAGE]
        plan = draft or (stored.plan if stored else None)
        if plan is None:
            raise TrainingConflictError("Missing plan for exercise selection")
        workflow = workflow or await self._repository.get_workflow(chat_id)
        if workflow is None:
            raise TrainingConflictError("Missing exercise selection workflow")
        filter_week = workflow.answers.get("swap_filter_week")
        eligible = {
            item.exercise_id
            for week in plan.weeks
            if not filter_week or str(week.week) == filter_week
            for day in week.days
            for item in day.exercises
        }
        exercise_filter = workflow.answers.get("swap_filter_exercise")
        if exercise_filter and int(exercise_filter) not in eligible:
            logger.warning("Ignoring invalid model exercise selection for chat %s", chat_id)
            workflow.answers.pop("swap_filter_exercise", None)
        picker = (
            Constants.TRAINING_SWAP_PICKER_WEEK.format(week=filter_week)
            if filter_week
            else Constants.TRAINING_SWAP_PICKER
        )
        prompts = {
            "exercise": picker,
            "week": Constants.TRAINING_SWAP_WEEK,
            "reason": Constants.TRAINING_SWAP_REASON,
            "input": Constants.TRAINING_SWAP_REASON_INPUT,
        }
        if workflow.answers.get("swap_step") in prompts:
            return [prompts[workflow.answers["swap_step"]]]
        workflow.answers["swap_step"] = "exercise"
        workflow.answers["swap_page"] = "0"
        await self._repository.save(chat_id, workflow)
        return [picker]

    async def _swap_button(
        self, chat_id: int, workflow: TrainingWorkflow, action: str, value: str
    ) -> list[str]:
        if workflow.state != "reviewing" or workflow.answers.get("safety_hold"):
            return [Constants.TRAINING_CALLBACK_INVALID]
        stored = await self._conversation.get_current_plan(chat_id)
        plan = workflow.base_draft or (stored.plan if stored else None)
        if plan is None:
            raise TrainingConflictError("Missing swap plan")
        step = workflow.answers.get("swap_step")
        if action == "page" and step == "exercise" and value.isdigit():
            page = int(value)
            if page * 8 >= len(plan.exercise_ids()):
                return [Constants.TRAINING_CALLBACK_INVALID]
            workflow.answers["swap_page"] = value
            await self._repository.save(chat_id, workflow)
            return await self._swap_question(chat_id, workflow.base_draft, workflow)
        elif (
            action == "exercise"
            and step == "exercise"
            and value.isdigit()
            and int(value) in plan.exercise_ids()
            and (
                not workflow.answers.get("swap_filter_exercise")
                or value == workflow.answers["swap_filter_exercise"]
            )
            and any(
                not workflow.answers.get("swap_filter_week")
                or str(week.week) == workflow.answers["swap_filter_week"]
                for week in plan.weeks
                if any(
                    item.exercise_id == int(value) for day in week.days for item in day.exercises
                )
            )
        ):
            workflow.answers["swap_exercise"] = value
            if workflow.base_draft is not None:
                workflow.answers.setdefault("swap_week", "1")
                return await self._swap_reason(chat_id, workflow)
            if workflow.answers.get("swap_filter_week"):
                return await self._swap_reason(chat_id, workflow)
            workflow.answers["swap_step"] = "week"
            message = Constants.TRAINING_SWAP_WEEK
        elif (
            action == "week"
            and step == "week"
            and value.isdigit()
            and any(
                week.week == int(value)
                and any(
                    item.exercise_id == int(workflow.answers["swap_exercise"])
                    for day in week.days
                    for item in day.exercises
                )
                for week in plan.weeks
            )
        ):
            workflow.answers["swap_week"] = value
            return await self._swap_reason(chat_id, workflow)
        elif action == "reason" and step == "reason" and value in Constants.TRAINING_SWAP_REASONS:
            if value in ("equipment", "other"):
                workflow.answers["swap_step"] = "input"
                message = Constants.TRAINING_SWAP_REASON_INPUT
            else:
                return await self._finish_swap_picker(
                    chat_id,
                    workflow,
                    Constants.TRAINING_SWAP_REASONS[value],
                    reason_source="preference_button" if value == "preference" else "free_text",
                )
        else:
            return [Constants.TRAINING_CALLBACK_INVALID]
        await self._repository.save(chat_id, workflow)
        return [message]

    async def _swap_reason(self, chat_id: int, workflow: TrainingWorkflow) -> list[str]:
        if workflow.answers.get("swap_message"):
            return await self._finish_swap_picker(
                chat_id, workflow, workflow.answers["swap_message"]
            )
        workflow.answers["swap_step"] = "reason"
        await self._repository.save(chat_id, workflow)
        return [Constants.TRAINING_SWAP_REASON]

    async def _finish_swap_picker(
        self,
        chat_id: int,
        workflow: TrainingWorkflow,
        reason: str,
        *,
        reason_source: SwapReasonSource = "free_text",
    ) -> list[str]:
        original = workflow.answers.pop("swap_user_text", "")
        if original:
            reason_source = "free_text"
        if original and original != reason:
            reason = f"{original}\n{reason}"
        request = f"{workflow.answers['swap_exercise']} {workflow.answers['swap_week']} {reason}"
        workflow.answers.pop("swap_step", None)
        workflow.answers.pop("swap_message", None)
        workflow = await self._repository.save(chat_id, workflow)
        return await self._prepare_swap(chat_id, workflow, request, reason_source=reason_source)

    async def _prepare_swap(
        self,
        chat_id: int,
        workflow: TrainingWorkflow,
        text: str,
        *,
        reason_source: SwapReasonSource = "free_text",
    ) -> list[str]:
        parts = text.split(maxsplit=2)
        if len(parts) != 3:
            return await self._swap_question(chat_id, workflow.base_draft, workflow)
        exercise_id = self._integer(parts[0])
        week = self._integer(parts[1])
        if week > 4:
            raise TrainingInputError(Constants.TRAINING_MESSAGES["invalid_week"])
        cycle = await self._repository.get_cycle(chat_id)
        if cycle and cycle.completed_at and workflow.base_draft is None:
            raise TrainingInputError(Constants.TRAINING_MESSAGES["closed_swap"])
        stored = await self._conversation.get_current_plan(chat_id)
        plan = workflow.base_draft or (stored.plan if stored else None)
        if plan is None or exercise_id not in plan.exercise_ids():
            raise TrainingInputError(Constants.TRAINING_MESSAGES["unknown_exercise"])
        if not any(
            item.exercise_id == exercise_id
            for block in plan.weeks
            if block.week >= week
            for day in block.days
            for item in day.exercises
        ):
            raise TrainingInputError(Constants.TRAINING_MESSAGES["no_pending_occurrences"])
        workflow.swap = SwapRequest(
            exercise_id=exercise_id, from_week=week, reason=parts[2], reason_source=reason_source
        )
        workflow = await self._repository.save(chat_id, workflow)
        return await self._generate(chat_id, workflow)

    @timed("swap", action="exercise_swap")
    async def _generate_swap(
        self,
        chat_id: int,
        workflow: TrainingWorkflow,
        profile: InterviewerProfile,
        plan: TrainingPlan,
    ) -> list[str]:
        request = workflow.swap
        if request is None:
            raise TrainingInputError(Constants.TRAINING_SWAP_QUESTION)
        trusted_preference = (
            request.reason_source == "preference_button"
            and request.reason == Constants.TRAINING_SWAP_REASONS["preference"]
            and not profile.injuries
            and not profile.flags.red
            and not workflow.review
            and not any(
                workflow.answers.get(key)
                for key in (
                    "swap_user_text",
                    "swap_message",
                    "swap_clarification",
                    "safety_hold",
                    "open_review",
                    "discomfort",
                )
            )
        )
        if trusted_preference:
            request.excluded_equipment = []
        else:
            constraints = await self._adaptation.extract_swap_constraints(profile, request)
            await self._account(chat_id, constraints.token_usages)
            if constraints.result.safety_hold:
                workflow.answers["safety_hold"] = "true"
                workflow.state = "reviewing"
                await self._repository.save(chat_id, workflow)
                return [Constants.TRAINING_SAFETY_MESSAGE]
            if constraints.result.clarification:
                workflow.answers["swap_clarification"] = constraints.result.clarification
                workflow.state = "reviewing"
                await self._repository.save(chat_id, workflow)
                return [constraints.result.clarification]
            request.excluded_equipment = constraints.result.excluded_equipment
        workflow.answers.pop("swap_clarification", None)
        source = await self._retriever.get_by_ids([request.exercise_id])
        if len(source) != 1:
            raise TrainingInputError(Constants.TRAINING_NO_ALTERNATIVES_MESSAGE)
        try:
            candidates = await self._retriever.retrieve_alternatives(
                profile, source[0], request.reason, excluded_equipment=request.excluded_equipment
            )
        except ValueError as error:
            raise TrainingInputError(
                Constants.TRAINING_MESSAGES["metadata_clarification"]
            ) from error
        if not candidates:
            raise TrainingInputError(Constants.TRAINING_NO_ALTERNATIVES_MESSAGE)
        candidates = [
            item for item in candidates if item.equipment not in request.excluded_equipment
        ]
        if not candidates:
            raise TrainingInputError(Constants.TRAINING_NO_ALTERNATIVES_MESSAGE)
        complete_catalogue = await self._retriever.get_by_ids(sorted(plan.exercise_ids()))
        proposal = await self._adaptation.propose_swap(
            profile, request, source[0], candidates, plan, catalogue=complete_catalogue
        )
        await self._account(chat_id, proposal.token_usages)
        if proposal.result.safety_hold:
            workflow.answers["safety_hold"] = "true"
            workflow.state = "reviewing"
            await self._repository.save(chat_id, workflow)
            return [Constants.TRAINING_SAFETY_MESSAGE]
        catalogue = [*complete_catalogue, *candidates]
        valid = []
        for option in proposal.result.options:
            try:
                with latency_phase("patch_validation"):
                    draft = self._swap_draft(plan, request, option.exercise)
            except ValueError:
                logger.warning("Rejected invalid swap for chat %s", chat_id, exc_info=True)
                continue
            evaluation = evaluate_turn(
                TrainerTurn(status="plan", reply="proposal", plan=draft, report="proposal"),
                profile,
                catalogue,
            )
            # Existing issues outside the changed prescription must not block every swap.
            baseline = evaluate_turn(
                TrainerTurn(status="plan", reply="base", plan=plan, report="base"),
                profile,
                catalogue,
            )
            old_errors = {
                (finding.rule, finding.where, finding.message)
                for finding in baseline.findings
                if finding.severity == Severity.ERROR
            }
            errors = [
                finding
                for finding in evaluation.findings
                if finding.severity == Severity.ERROR
                and (finding.rule, finding.where, finding.message) not in old_errors
            ]
            if not errors:
                valid.append(option)
        if not valid:
            raise TrainingInputError(Constants.TRAINING_NO_ALTERNATIVES_MESSAGE)
        workflow.options = valid
        workflow.effective_profile = profile
        workflow.state = "awaiting_confirmation"
        workflow.answers["catalogue_ids"] = ",".join(str(item.id) for item in candidates)
        if proposal.trace:
            workflow.prompt_trace = asdict(proposal.trace)
            workflow.prompt_trace["retrieved_exercise_ids"] = list(
                proposal.trace.retrieved_exercise_ids
            )
            workflow.generation_traces.append(workflow.prompt_trace.copy())
        workflow = await self._repository.save(chat_id, workflow)
        return self._proposal_messages(workflow)

    async def _select(
        self, chat_id: int, workflow: TrainingWorkflow, workflow_id: int, option: int
    ) -> list[str]:
        if (
            workflow.id != workflow_id
            or (workflow.kind != "exercise_swap" and workflow.base_draft is None)
            or workflow.state != "awaiting_confirmation"
            or workflow.swap is None
        ):
            raise TrainingConflictError("Unknown pending swap")
        if not 1 <= option <= len(workflow.options):
            raise TrainingInputError(Constants.TRAINING_MESSAGES["invalid_option"])
        stored = await self._conversation.get_current_plan(chat_id)
        if stored is None:
            raise TrainingConflictError("Missing base plan")
        chosen = workflow.options[option - 1]
        workflow.answers["selected_exercise_id"] = str(chosen.exercise.exercise_id)
        workflow.draft = self._swap_draft(
            workflow.base_draft or stored.plan, workflow.swap, chosen.exercise
        )
        workflow.report = Constants.TRAINING_MESSAGES["swap_report"].format(
            source=workflow.swap.exercise_id,
            name=chosen.exercise.name,
            week=workflow.swap.from_week,
            reason=chosen.rationale,
            sets=chosen.exercise.sets,
            reps=chosen.exercise.reps,
            rest=chosen.exercise.rest_seconds,
            rpe=chosen.exercise.rpe or Constants.TRAINING_MESSAGES["unspecified_rpe"],
        )
        if workflow.base_report:
            workflow.report = workflow.base_report + "\n" + workflow.report
        workflow = await self._repository.save(chat_id, workflow)
        return self._proposal_messages(workflow)

    @staticmethod
    def _swap_draft(
        plan: TrainingPlan, request: SwapRequest, replacement: PlannedExercise
    ) -> TrainingPlan:
        draft = apply_swap(plan, request, replacement)
        for week in draft.weeks:
            if week.week >= request.from_week:
                for day in week.days:
                    if any(item.exercise_id == replacement.exercise_id for item in day.exercises):
                        day.estimated_minutes = max(
                            15, math.ceil(estimate_session_minutes(day.exercises))
                        )
        return TrainingPlan.model_validate(draft.model_dump())

    @staticmethod
    def _proposal_messages(workflow: TrainingWorkflow) -> list[str]:
        if workflow.draft is None:
            return [
                Constants.TRAINING_MESSAGES["alternatives_header"]
                + "\n".join(
                    f"{index}. {option.exercise.name}: {option.rationale}; "
                    f"{option.exercise.sets} × {option.exercise.reps}, "
                    f"descanso {option.exercise.rest_seconds}s."
                    for index, option in enumerate(workflow.options, 1)
                ),
                Constants.TRAINING_MESSAGES["choose"].format(id=workflow.id),
            ]
        return [preview(workflow)]
