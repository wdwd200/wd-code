from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBundle:
    text: str = ""


class ContextProvider:
    def build(self, *, user_input: str, conversation) -> ContextBundle:
        return ContextBundle()
