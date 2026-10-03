from fitcoach.domain.agents import Agent, AgentType, InterviewerAgent, TrainerAgent


class TestInterviewerAgent:
    def test_stores_the_given_system_prompt_as_is(self) -> None:
        agent = InterviewerAgent("assembled prompt with {{rag_context}} pending")

        assert agent.system_prompt == "assembled prompt with {{rag_context}} pending"

    def test_is_an_agent(self) -> None:
        agent = InterviewerAgent("prompt")

        assert isinstance(agent, Agent)

    def test_is_tagged_as_the_interviewer_agent_type(self) -> None:
        agent = InterviewerAgent("prompt")

        assert agent.agent_type is AgentType.INTERVIEWER


class TestTrainerAgent:
    def test_stores_the_given_system_prompt_as_is(self) -> None:
        agent = TrainerAgent("assembled prompt with {{rag_context}} pending")

        assert agent.system_prompt == "assembled prompt with {{rag_context}} pending"

    def test_is_an_agent(self) -> None:
        assert isinstance(TrainerAgent("prompt"), Agent)

    def test_is_tagged_as_the_trainer_agent_type(self) -> None:
        assert TrainerAgent("prompt").agent_type is AgentType.TRAINER

    def test_insert_context_fills_the_rag_placeholder_without_mutating_the_prompt(self) -> None:
        # El contexto es por peticion: la misma instancia se reutiliza entre llamadas.
        agent = TrainerAgent("catalogo:\n{{rag_context}}\nfin")

        first = agent.insert_context("id: 1 | name: push up")

        assert "id: 1 | name: push up" in first
        assert "{{rag_context}}" not in first
        assert "{{rag_context}}" in agent.system_prompt
