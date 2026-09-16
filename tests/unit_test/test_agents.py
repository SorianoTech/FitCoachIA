from fitcoach.domain.agents import Agent, AgentType, InterviewerAgent


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
