"""Agent entities: each holds its composed LLM system prompt."""

from enum import Enum


class AgentType(Enum):
    """Identifies which agent handled a turn, for logs/spans/token_usage rows.

    NUTRITIONIST/COACH are placeholders: no agent implements them yet, but
    instrumentation can already tag turns without waiting for their code.
    """

    INTERVIEWER = "interviewer"
    TRAINER = "trainer"
    NUTRITIONIST = "nutritionist"
    COACH = "coach"


class Agent:
    def __init__(self, system_prompt: str, agent_type: AgentType) -> None:
        self.system_prompt = system_prompt
        self.agent_type = agent_type

    def insert_context(self, rag_context: str = "") -> str:
        """Return ``system_prompt`` with the RAG placeholder filled in.

        Does not mutate ``system_prompt``: retrieved context is per-request,
        so the same agent instance is reused across calls with fresh context.
        """
        return self.system_prompt.replace("{{rag_context}}", rag_context)


class InterviewerAgent(Agent):
    """Entity for the Interviewer (Agent 1 / Secretario).

    ``system_prompt`` already has its skill injected; ``{{rag_context}}`` is
    left unresolved until a future RAG step fills it in.
    """

    def __init__(self, system_prompt: str) -> None:
        super().__init__(system_prompt, AgentType.INTERVIEWER)


class TrainerAgent(Agent):
    """Entity for the Trainer (Agent 2 / Entrenador).

    Unlike the Interviewer, this agent always runs with a filled
    ``{{rag_context}}``: its exercise choices must come from the corpus, not
    from the model's memory.
    """

    def __init__(self, system_prompt: str) -> None:
        super().__init__(system_prompt, AgentType.TRAINER)
