"""Optional LLM access. With no ANTHROPIC_API_KEY everything falls back to the rule engine."""
from pydantic import BaseModel

from app.core.config import settings


def enabled() -> bool:
    return bool(settings.anthropic_api_key)


def _client():
    import anthropic

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def structured(system: str, user: str, model_cls: type[BaseModel]) -> BaseModel:
    """Ask for an answer that must fit a Pydantic model (forced tool call)."""
    resp = await _client().messages.create(
        model=settings.llm_model,
        max_tokens=1500,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[{"name": "answer", "description": "Return the answer", "input_schema": model_cls.model_json_schema()}],
        tool_choice={"type": "tool", "name": "answer"},
    )
    for block in resp.content:
        if block.type == "tool_use":
            return model_cls.model_validate(block.input)
    raise RuntimeError("model did not return a structured answer")


async def text(system: str, user: str) -> str:
    resp = await _client().messages.create(
        model=settings.llm_model,
        max_tokens=2000,
        temperature=0.2,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")
