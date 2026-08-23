class IAMessage:
    def __init__(self, role: str = "user", message: str = ""):
        self.__role = role
        self.__message = message

    def to_dict(self) -> dict[str, str]:
        return {"role": self.__role, "content": self.__message}


class IAInput:
    def __init__(self, input: list[IAMessage] | None = None):
        self.__input = input if input is not None else []

    def get_input(self) -> list[dict[str, str]]:
        return [message.to_dict() for message in self.__input]
