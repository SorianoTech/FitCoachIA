from fitcoach.domain.entities import IAInput, IAMessage


class TestIAMessage:
    def test_to_dict_returns_role_and_content(self) -> None:
        message = IAMessage(role="system", message="be helpful")
        assert message.to_dict() == {"role": "system", "content": "be helpful"}

    def test_defaults_to_user_role_and_empty_message(self) -> None:
        message = IAMessage()
        assert message.role == "user"
        assert message.message == ""


class TestIAInput:
    def test_get_message_by_role_returns_matching_content(self) -> None:
        llm_input = IAInput([
            IAMessage(role="system", message="be helpful"),
            IAMessage(role="user", message="hello"),
        ])
        assert llm_input.get_message_by_role("system") == "be helpful"

    def test_get_message_by_role_returns_empty_string_when_role_is_absent(self) -> None:
        llm_input = IAInput([IAMessage(role="user", message="hello")])
        assert llm_input.get_message_by_role("assistant") == ""

    def test_get_message_by_role_returns_first_match_when_role_repeats(self) -> None:
        llm_input = IAInput([
            IAMessage(role="user", message="first"),
            IAMessage(role="user", message="second"),
        ])
        assert llm_input.get_message_by_role("user") == "first"

    def test_get_user_message_returns_the_user_content(self) -> None:
        llm_input = IAInput([
            IAMessage(role="system", message="be helpful"),
            IAMessage(role="user", message="hello"),
        ])
        assert llm_input.get_user_message() == "hello"

    def test_get_user_message_returns_empty_string_when_no_user_message_exists(self) -> None:
        llm_input = IAInput([IAMessage(role="system", message="be helpful")])
        assert llm_input.get_user_message() == ""

    def test_get_user_message_returns_empty_string_on_empty_input(self) -> None:
        assert IAInput().get_user_message() == ""
