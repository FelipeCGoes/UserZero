import os

from langchain_openai import ChatOpenAI


def get_llm(temperature: float = 0.0, max_tokens: int = 16000) -> ChatOpenAI:
    """Single Featherless-backed model shared by every agent and judge in the pipeline.

    max_tokens defaults well above Featherless's own default (4096) — some models
    spend a chunk of the completion budget on hidden reasoning before ever emitting
    visible content or a tool call, and hitting the cap mid-turn produces a silent,
    empty response (finish_reason="length", content="", tool_calls=[]) with no error
    to catch.
    """
    return ChatOpenAI(
        base_url=os.environ["FEATHERLESS_BASE_URL"],
        api_key=os.environ["FEATHERLESS_API_KEY"],
        model=os.environ["MODEL"],
        temperature=temperature,
        max_tokens=max_tokens,
    )
