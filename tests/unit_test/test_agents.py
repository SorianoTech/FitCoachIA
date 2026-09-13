from fitcoach.domain.agents import Agent, InterviewerAgent


class TestInterviewerAgent:
    def test_stores_the_given_system_prompt_as_is(self) -> None:
        agent = InterviewerAgent("assembled prompt with {{rag_context}} pending")

        assert agent.system_prompt == "assembled prompt with {{rag_context}} pending"

    def test_is_an_agent(self) -> None:
        agent = InterviewerAgent("prompt")

        assert isinstance(agent, Agent)
