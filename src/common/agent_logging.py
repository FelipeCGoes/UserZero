import json
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage


def preview(text: str, n: int = 240) -> str:
    """Collapse whitespace and hard-cut at n chars. Used for tool input/output only —
    assistant text is printed in full, never truncated."""
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[:n] + "..."


def _json_default(obj):
    """LangChain messages are pydantic models — dump them to plain dicts instead of
    falling back to repr(), or transcript.jsonl silently degrades from structured JSON
    into unparseable Python object reprs."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


async def run_with_console_log(agent, inputs: dict, config: dict | None = None,
                                transcript_path: Path | None = None) -> dict:
    """Streams a LangGraph agent (from langchain.agents.create_agent) and prints a
    readable, tagged projection to stdout while writing the full raw event stream
    verbatim to transcript_path (one JSON object per line). Console is always a
    strict subset of the transcript — nothing here is computed for console-only
    purposes.

    Returns {"messages": [...]} shaped like agent.ainvoke's result, so it's a
    drop-in replacement for `await agent.ainvoke(inputs, config=config)`.

    Tags:
      [ASSISTANT]      full, untruncated assistant text (silent if blank)
      [TOOL <name>]    truncated preview of the tool call's JSON args
      [RESULT]         truncated preview of the tool's return value
      [RUN <STATUS>]   printed once at the end: SUCCESS or ERROR, then token
                       totals (if the model reports usage) and turn count
    """
    transcript = transcript_path.open("w", encoding="utf-8") if transcript_path else None
    turns = 0
    input_tokens = output_tokens = 0
    status = "success"
    messages: list = []

    try:
        async for chunk in agent.astream(inputs, config=config, stream_mode="updates"):
            if transcript:
                transcript.write(json.dumps(chunk, default=_json_default) + "\n")

            for node_output in chunk.values():
                for message in (node_output or {}).get("messages", []):
                    messages.append(message)

                    if isinstance(message, AIMessage):
                        turns += 1
                        text = message.content if isinstance(message.content, str) else ""
                        if text.strip():
                            print("\n[ASSISTANT]")
                            print(text)
                        for call in message.tool_calls or []:
                            args = json.dumps(call["args"], default=str)
                            print(f"\n[TOOL {call['name']}] {preview(args)}")
                        usage = getattr(message, "usage_metadata", None) or {}
                        input_tokens += usage.get("input_tokens", 0) or 0
                        output_tokens += usage.get("output_tokens", 0) or 0

                    elif isinstance(message, ToolMessage):
                        content = message.content if isinstance(message.content, str) \
                            else json.dumps(message.content, default=str)
                        print(f"[RESULT] {preview(content)}")
    except Exception:
        status = "error"
        raise
    finally:
        print(f"\n[RUN {status.upper()}]")
        if input_tokens or output_tokens:
            print(f"Tokens: {input_tokens} in / {output_tokens} out")
        print(f"Turns: {turns}")
        if transcript:
            transcript.close()

    return {"messages": messages}
