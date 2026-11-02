"""Responses API loop that executes local (in-container) function tools.

MCP tools (Microsoft 365, Foundry Toolbox) are executed server-side by Foundry
within a single ``responses.create`` call. Function tools are returned to us as
``function_call`` output items; we run them locally and send the results back
with ``previous_response_id`` until the model produces a final answer.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Awaitable, Callable, Union

logger = logging.getLogger(__name__)

# Executors may be synchronous (in-memory FSI tools) or async (tools that call Azure).
FunctionExecutor = Callable[[str, str], Union[dict[str, Any], Awaitable[dict[str, Any]]]]


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def function_calls(response: Any) -> list[Any]:
    return [item for item in (_get(response, "output") or []) if _get(item, "type") == "function_call"]


async def run_responses_with_tools(
    client: Any,
    *,
    request_args: dict[str, Any],
    execute_function: FunctionExecutor,
    max_rounds: int = 8,
) -> Any:
    """Call ``client.responses.create`` and resolve function calls until done."""
    response = await client.responses.create(**request_args)
    for round_number in range(1, max_rounds + 1):
        calls = function_calls(response)
        if not calls:
            return response
        outputs = []
        for call in calls:
            name = _get(call, "name") or ""
            arguments = _get(call, "arguments") or "{}"
            result = execute_function(name, arguments)
            if inspect.isawaitable(result):
                result = await result
            outputs.append({
                "type": "function_call_output",
                "call_id": _get(call, "call_id"),
                "output": json.dumps(result, default=str),
            })
        logger.info("Tool round %d: executed %d function call(s)", round_number, len(outputs))
        follow_up = {k: v for k, v in request_args.items() if k not in {"input", "previous_response_id"}}
        follow_up["input"] = outputs
        follow_up["previous_response_id"] = _get(response, "id")
        response = await client.responses.create(**follow_up)
    if function_calls(response):
        logger.warning("Stopped after %d tool rounds with function calls still pending", max_rounds)
    return response
