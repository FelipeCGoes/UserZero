import os

from langchain_openai import ChatOpenAI


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    """Single Featherless-backed model shared by every agent and judge in the pipeline."""
    return ChatOpenAI(
        base_url=os.environ["FEATHERLESS_BASE_URL"],
        api_key=os.environ["FEATHERLESS_API_KEY"],
        model=os.environ["MODEL"],
        temperature=temperature,
    )
