import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

load_dotenv()

@tool
def word_count(text: str) -> int:
    """Count the number of words in a piece of text."""
    return len(text.split())

agent = create_agent(
  ChatOpenAI(
    base_url="https://api.featherless.ai/v1",
    api_key=os.environ["FEATHERLESS_API_KEY"],
    model="Qwen/Qwen2.5-7B-Instruct",
  ), 
  tools=[word_count]
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "How many words are in the sentence 'the quick brown fox jumps'?"}]}
)
print(result["messages"][-1].content)