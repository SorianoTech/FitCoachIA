"""Agent entities: each holds its composed LLM system prompt."""

RAG_CONTEXT_PLACEHOLDER = "{{rag_context}}"


class Agent:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def insert_context(self, rag_context: str = "") -> str:
        """Return ``system_prompt`` with the RAG placeholder filled in.

        Does not mutate ``system_prompt``: retrieved context is per-request,
        so the same agent instance is reused across calls with fresh context.
        """
        return self.system_prompt.replace(RAG_CONTEXT_PLACEHOLDER, rag_context)


class InterviewerAgent(Agent):
    """Entity for the Interviewer (Agent 1 / Secretario).

    ``system_prompt`` already has its skill injected; ``{{rag_context}}`` is
    left unresolved until a future RAG step fills it in.
    """
