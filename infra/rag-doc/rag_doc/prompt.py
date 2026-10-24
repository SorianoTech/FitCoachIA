"""Prompt composition: system rules + numbered context + short history + the question."""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from rag_doc.texts import REWRITE_PROMPT, SYSTEM_PROMPT


def format_context(passages: list[dict[str, Any]]) -> str:
    blocks = []
    for number, passage in enumerate(passages, start=1):
        title = (
            f"{passage['source']} — {passage['heading']}"
            if passage["heading"]
            else passage["source"]
        )
        blocks.append(f"[{number}] {title}\n{passage['text']}")
    return "\n\n".join(blocks)


def build_messages(
    question: str, history: list[dict[str, str]], passages: list[dict[str, Any]]
) -> list[BaseMessage]:
    system = f"{SYSTEM_PROMPT}\n\nContexto:\n{format_context(passages)}"
    turns: list[BaseMessage] = [
        HumanMessage(turn["content"]) if turn["role"] == "user" else AIMessage(turn["content"])
        for turn in history
    ]
    return [SystemMessage(system), *turns, HumanMessage(question)]


def build_rewrite_messages(question: str, history: list[dict[str, str]]) -> list[BaseMessage]:
    transcript = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
    return [
        SystemMessage(REWRITE_PROMPT),
        HumanMessage(f"Conversación:\n{transcript}\n\nÚltima pregunta: {question}"),
    ]
