"""Training mutations require a persisted proposal and an explicit confirmation."""

import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime

from fitcoach.domain.agent_errors import AgentError
from fitcoach.domain.constants import Constants
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.domain.trainer_plan import PlannedExercise, TrainerTurn, TrainingPlan
from fitcoach.domain.training_lifecycle import (
    SwapRequest,
    TrainingAdaptationContext,
    TrainingReview,
    TrainingWorkflow,
    apply_swap,
    prescribed_summary,
    utc_now,
)
from fitcoach.repository.conversation_repository import ConversationRepository
from fitcoach.repository.training_repository import TrainingConflictError, TrainingRepository
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever
from fitcoach.service.agent.plan_evaluator import Severity, estimate_session_minutes, evaluate_turn
from fitcoach.service.agent.trainer_chain import TrainerChain
from fitcoach.service.agent.training_adaptation_chain import TrainingAdaptationChain

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
    ) -> None:
        self._repository = repository
        self._conversation = conversation
        self._trainer = trainer
        self._retriever = retriever
        self._adaptation = adaptation
        self._limits = limits
        self._clock = clock

    async def profile(self, chat_id: int) -> InterviewerProfile | None:
        return await self._repository.effective_profile(
            chat_id
        ) or await self._conversation.get_interviewer_profile(chat_id)

    async def has_workflow(self, chat_id: int) -> bool:
        return await self._repository.get_workflow(chat_id) is not None

    async def remind_on_interaction(
        self,
        chat_id: int,
        thread_id: int | None,
        send: Callable[[int, int | None, str], Awaitable[None]],
    ) -> None:
        delivery = await self._repository.reserve_interaction_reminder(
            chat_id, thread_id, self._clock()
        )
        if delivery is None:
            return
        try:
            await send(chat_id, thread_id, Constants.TRAINING_DUE_MESSAGE)
        except Exception:
            logger.exception("Failed to deliver interaction reminder for chat %s", chat_id)
            await self._repository.finish_reminder(delivery, retry_at=self._clock())
            return
        await self._repository.finish_reminder(delivery)

    async def status(self, chat_id: int) -> list[str]:
        cycle = await self._repository.get_cycle(chat_id)
        if cycle is None:
            return [Constants.NO_PLAN_MESSAGE]
        if cycle.started_at is None:
            return [Constants.TRAINING_LEGACY_MESSAGE]
        if cycle.completed_at:
            return [
                "Cierre confirmado. Envía /train para continuar la revisión del siguiente bloque."
            ]
        if cycle.due(self._clock()):
            return [Constants.TRAINING_DUE_MESSAGE]
        return [
            f"Mesociclo iniciado el {cycle.started_at.date()}; cierre previsto: "
            f"{cycle.expected_end_at.date() if cycle.expected_end_at else 'sin confirmar'}. "
            "La ejecución no se registra automáticamente. Envía /train si ya has terminado."
        ]

    async def handle(self, chat_id: int, text: str) -> list[str]:
        try:
            return await self._handle(chat_id, text)
        except TrainingConflictError:
            logger.warning("Training proposal conflict for chat %s", chat_id, exc_info=True)
            return [Constants.TRAINING_CONFLICT_MESSAGE]
        except TrainingInputError as error:
            logger.warning("Training action needs clarification for chat %s: %s", chat_id, error)
            return [str(error)]

    async def _handle(self, chat_id: int, text: str) -> list[str]:
        tokens = text.split()
        command = tokens[0] if tokens else ""
        arguments = tokens[1:]
        action = arguments[0].lower() if command == "/train" and arguments else ""
        if command == "/progress":
            return await self.status(chat_id)
        if action == "cancelar":
            await self._repository.cancel(chat_id)
            return [Constants.TRAINING_CANCELLED_MESSAGE]
        if action == "avisos":
            if len(arguments) != 2 or arguments[1] not in ("on", "off"):
                raise TrainingInputError("Usa /train avisos on|off.")
            await self._repository.set_reminders(chat_id, arguments[1] == "on")
            return ["Preferencia de avisos guardada."]
        if action in ("inicio", "posponer"):
            if len(arguments) != 2:
                raise TrainingInputError("Indica una fecha con formato AAAA-MM-DD.")
            date = self._date(arguments[1])
            if action == "inicio":
                if date > self._clock():
                    raise TrainingInputError(
                        "El inicio del plan anterior no puede estar en el futuro."
                    )
                await self._repository.set_start(chat_id, date)
            else:
                if date <= self._clock():
                    raise TrainingInputError("La nueva fecha prevista debe estar en el futuro.")
                await self._repository.postpone(chat_id, date)
                await self._repository.cancel(chat_id)
            return await self.status(chat_id)
        if action == "confirmar":
            if len(arguments) not in (2, 3):
                raise TrainingInputError("Usa /train confirmar PROPUESTA [AAAA-MM-DD].")
            start = self._date(arguments[2]) if len(arguments) == 3 else self._clock()
            if start.date() < self._clock().date():
                raise TrainingInputError("El nuevo mesociclo no puede empezar en el pasado.")
            await self._repository.accept(chat_id, self._integer(arguments[1]), start)
            return [Constants.TRAINING_ACCEPTED_MESSAGE]
        workflow = await self._repository.get_workflow(chat_id)
        if action == "editar":
            if (
                workflow is None
                or workflow.kind != "renewal"
                or len(arguments) < 3
                or arguments[1] not in Constants.TRAINING_REVIEW_QUESTIONS
            ):
                raise TrainingInputError(Constants.TRAINING_CONTROLS_MESSAGE)
            workflow.answers[arguments[1]] = " ".join(arguments[2:])
            workflow.answers.pop("safety_hold", None)
            workflow.review = None
            workflow.effective_profile = None
            workflow.draft = None
            workflow.report = None
            workflow.state = "reviewing"
            workflow.lease_until = None
            workflow = await self._repository.save(chat_id, workflow)
            return [await self._next_question(chat_id, workflow)]
        if action == "elegir":
            if workflow is None or len(arguments) != 3:
                raise TrainingInputError("Usa /train elegir PROPUESTA OPCIÓN.")
            return await self._select(
                chat_id, workflow, self._integer(arguments[1]), self._integer(arguments[2])
            )
        if command == "/train" and action not in ("", "cambiar", "revisar"):
            return [Constants.TRAINING_CONTROLS_MESSAGE]
        if workflow is None:
            workflow = await self._repository.start(
                chat_id, "exercise_swap" if action == "cambiar" else "renewal"
            )
        if action == "cambiar" and workflow.kind != "exercise_swap":
            raise TrainingInputError(
                "Hay una revisión abierta. Indica los cambios en ella o usa /train cancelar primero."
            )
        if workflow.state == "awaiting_confirmation":
            return self._proposal_messages(workflow)
        if workflow.state == "generating":
            if workflow.lease_until and workflow.lease_until > self._clock():
                return [Constants.TRAINING_BUSY_MESSAGE]
            return await self._generate(chat_id, workflow)
        if workflow.kind == "exercise_swap":
            request_text = " ".join(arguments[1:]) if action == "cambiar" else text
            if command == "/train" and not request_text:
                return await self._swap_question(chat_id)
            return await self._prepare_swap(chat_id, workflow, request_text)
        if command == "/train":
            return [await self._next_question(chat_id, workflow)]
        return await self._review_answer(chat_id, workflow, text)

    @staticmethod
    def _integer(value: str) -> int:
        try:
            result = int(value)
        except ValueError as error:
            raise TrainingInputError("Indica un identificador numérico válido.") from error
        if result < 1:
            raise TrainingInputError("El identificador debe ser positivo.")
        return result

    @staticmethod
    def _date(value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as error:
            raise TrainingInputError(
                "La fecha debe ser válida y usar el formato AAAA-MM-DD (UTC)."
            ) from error

    async def _next_question(self, chat_id: int, workflow: TrainingWorkflow) -> str:
        cycle = await self._repository.get_cycle(chat_id)
        if "closed" not in workflow.answers and (cycle is None or cycle.completed_at is None):
            return Constants.TRAINING_CLOSURE_QUESTION
        if workflow.answers.get("safety_hold"):
            return Constants.TRAINING_SAFETY_MESSAGE
        for field, question in Constants.TRAINING_REVIEW_QUESTIONS.items():
            if field not in workflow.answers:
                return question
        return (
            "Revisión recogida. Responde «generar» para reintentar el borrador o /train cancelar."
        )

    async def _review_answer(
        self, chat_id: int, workflow: TrainingWorkflow, text: str
    ) -> list[str]:
        cycle = await self._repository.get_cycle(chat_id)
        if "closed" not in workflow.answers and (cycle is None or cycle.completed_at is None):
            if text.lower().strip(" .!¡¿?") not in ("sí", "si", "terminado", "he terminado"):
                return [Constants.TRAINING_CLOSURE_QUESTION]
            await self._repository.close_cycle(chat_id, self._clock())
            workflow.answers["closed"] = "confirmed"
            workflow = await self._repository.save(chat_id, workflow)
            return [await self._next_question(chat_id, workflow)]
        if workflow.answers.get("safety_hold"):
            return [Constants.TRAINING_SAFETY_MESSAGE]
        for field in Constants.TRAINING_REVIEW_QUESTIONS:
            if field not in workflow.answers:
                workflow.answers[field] = text
                workflow = await self._repository.save(chat_id, workflow)
                if any(key not in workflow.answers for key in Constants.TRAINING_REVIEW_QUESTIONS):
                    return [await self._next_question(chat_id, workflow)]
                break
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
        if await self._quota(chat_id):
            return [Constants.QUOTA_SOFT_MESSAGE]
        workflow = await self._repository.claim_generation(chat_id, workflow.id)
        try:
            profile = await self.profile(chat_id)
            stored = await self._conversation.get_current_plan(chat_id)
            if profile is None or stored is None:
                raise TrainingInputError(Constants.NO_PROFILE_MESSAGE)
            if workflow.kind == "exercise_swap":
                return await self._generate_swap(chat_id, workflow, profile, stored.plan)
            if workflow.review is None:
                extraction = await self._adaptation.extract_review(profile, workflow.answers)
                await self._account(chat_id, extraction.token_usages)
                workflow.review = TrainingReview(
                    **{key: workflow.answers[key] for key in Constants.TRAINING_REVIEW_QUESTIONS},
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
                workflow = await self._repository.save(chat_id, workflow)
            effective = workflow.effective_profile or profile
            previous = await self._retriever.get_by_ids(sorted(stored.plan.exercise_ids()))
            candidates = await self._retriever.retrieve(effective)
            catalogue = {item.id: item for item in [*previous, *candidates]}
            if not catalogue:
                raise TrainingInputError(Constants.TRAINER_UNAVAILABLE_MESSAGE)
            if workflow.review is None:
                raise TrainingConflictError("Validated review disappeared during generation")
            context = TrainingAdaptationContext(
                profile=effective,
                previous_plan=stored.plan,
                previous_version=stored.version,
                review=workflow.review,
                prescribed_summary=prescribed_summary(stored.plan, previous),
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

    async def _swap_question(self, chat_id: int) -> list[str]:
        stored = await self._conversation.get_current_plan(chat_id)
        if stored is None:
            return [Constants.NO_PLAN_MESSAGE]
        names = {
            exercise.exercise_id: exercise.name
            for week in stored.plan.weeks
            for day in week.days
            for exercise in day.exercises
        }
        return [
            Constants.TRAINING_SWAP_QUESTION,
            "\n".join(f"{key}: {name}" for key, name in names.items()),
        ]

    async def _prepare_swap(self, chat_id: int, workflow: TrainingWorkflow, text: str) -> list[str]:
        parts = text.split(maxsplit=2)
        if len(parts) != 3:
            return await self._swap_question(chat_id)
        exercise_id = self._integer(parts[0])
        week = self._integer(parts[1])
        if week > 4:
            raise TrainingInputError("La semana actual debe estar entre 1 y 4.")
        if any(word in parts[2].lower() for word in ("dolor", "pain", "lesión", "lesion", "mareo")):
            return [Constants.TRAINING_SAFETY_MESSAGE]
        cycle = await self._repository.get_cycle(chat_id)
        if cycle and cycle.completed_at:
            raise TrainingInputError(
                "El ciclo está cerrado. Cancela la sustitución y usa /train para renovar."
            )
        stored = await self._conversation.get_current_plan(chat_id)
        if stored is None or exercise_id not in stored.plan.exercise_ids():
            raise TrainingInputError("Ese ejercicio no pertenece al plan vigente.")
        if not any(
            item.exercise_id == exercise_id
            for block in stored.plan.weeks
            if block.week >= week
            for day in block.days
            for item in day.exercises
        ):
            raise TrainingInputError(
                "No hay ocurrencias de ese ejercicio en las semanas pendientes indicadas."
            )
        workflow.swap = SwapRequest(exercise_id=exercise_id, from_week=week, reason=parts[2])
        workflow = await self._repository.save(chat_id, workflow)
        return await self._generate(chat_id, workflow)

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
        source = await self._retriever.get_by_ids([request.exercise_id])
        if len(source) != 1:
            raise TrainingInputError(Constants.TRAINING_NO_ALTERNATIVES_MESSAGE)
        try:
            candidates = await self._retriever.retrieve_alternatives(
                profile, source[0], request.reason
            )
        except ValueError as error:
            raise TrainingInputError(
                "Necesito aclarar el material o los metadatos del ejercicio antes de proponer alternativas."
            ) from error
        if not candidates:
            raise TrainingInputError(Constants.TRAINING_NO_ALTERNATIVES_MESSAGE)
        proposal = await self._adaptation.propose_swap(profile, request, source[0], candidates)
        await self._account(chat_id, proposal.token_usages)
        if proposal.result.safety_hold:
            raise TrainingInputError(Constants.TRAINING_SAFETY_MESSAGE)
        complete_catalogue = await self._retriever.get_by_ids(sorted(plan.exercise_ids()))
        catalogue = [*complete_catalogue, *candidates]
        valid = []
        for option in proposal.result.options:
            try:
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
        workflow = await self._repository.save(chat_id, workflow)
        return self._proposal_messages(workflow)

    async def _select(
        self, chat_id: int, workflow: TrainingWorkflow, workflow_id: int, option: int
    ) -> list[str]:
        if (
            workflow.id != workflow_id
            or workflow.kind != "exercise_swap"
            or workflow.state != "awaiting_confirmation"
            or workflow.swap is None
        ):
            raise TrainingConflictError("Unknown pending swap")
        if not 1 <= option <= len(workflow.options):
            raise TrainingInputError("Elige una de las opciones propuestas.")
        stored = await self._conversation.get_current_plan(chat_id)
        if stored is None:
            raise TrainingConflictError("Missing base plan")
        chosen = workflow.options[option - 1]
        workflow.draft = self._swap_draft(stored.plan, workflow.swap, chosen.exercise)
        workflow.report = (
            f"Sustitución: {workflow.swap.exercise_id} → {chosen.exercise.name}, desde la semana "
            f"{workflow.swap.from_week}. {chosen.rationale} "
            f"Prescripción: {chosen.exercise.sets} series, {chosen.exercise.reps} repeticiones, "
            f"{chosen.exercise.rest_seconds}s de descanso; RPE {chosen.exercise.rpe or 'no indicado'}."
        )
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
                "Alternativas propuestas; todavía no se ha modificado el plan:\n"
                + "\n".join(
                    f"{index}. {option.exercise.name}: {option.rationale}; "
                    f"{option.exercise.sets} × {option.exercise.reps}, "
                    f"descanso {option.exercise.rest_seconds}s."
                    for index, option in enumerate(workflow.options, 1)
                ),
                f"Elige con /train elegir {workflow.id} OPCIÓN o /train cancelar.",
            ]
        result = [f"Borrador {workflow.id} (no activo):\n{workflow.report}"]
        if workflow.answers.get("interpretation"):
            result.append(workflow.answers["interpretation"])
        result.append(
            f"Revisa los cambios y el contexto antes de aceptar. Usa /train confirmar {workflow.id}"
            " [AAAA-MM-DD] para indicar el inicio del nuevo bloque, o /train cancelar. "
            "Las sustituciones conservan las fechas del bloque."
        )
        return result
