class IAMessage:
    def __init__(self, role: str = "user", message: str = ""):
        self.__role = role
        self.__message = message

    def to_dict(self) -> dict[str, str]:
        return {"role": self.__role, "content": self.__message}

    @property
    def role(self) -> str:
        return self.__role

    @property
    def message(self) -> str:
        return self.__message


class IAInput:
    def __init__(self, input: list[IAMessage] | None = None):
        self.__input = input if input is not None else []

    def get_input(self) -> list[dict[str, str]]:
        return [message.to_dict() for message in self.__input]

    def get_message_by_role(self, role: str) -> str:
        return next((message.message for message in self.__input if message.role == role), "")

    def get_user_message(self) -> str:
        return self.get_message_by_role("user")
