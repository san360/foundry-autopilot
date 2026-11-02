import asyncio
import json
from types import SimpleNamespace

from fincrime_autopilot.fsi_data import load_bank_data
from fincrime_autopilot.fsi_tools import TOOL_SCHEMAS, ToolContext, execute_tool
from fincrime_autopilot.tool_loop import function_calls, run_responses_with_tools


class FakeResponses:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.scripted.pop(0)


def call(call_id, name, args):
    return SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=json.dumps(args))


def response(response_id, *items):
    return SimpleNamespace(id=response_id, output=list(items))


def test_loop_executes_function_calls_and_chains_previous_response_id():
    responses = FakeResponses([
        response("r1", call("c1", "get_alert", {"alert_id": "1043"}), call("c2", "get_policy", {"query": "TM-STR-03"})),
        response("r2", call("c3", "compute_risk_indicators", {"alert_id": "ALR-2026-1043"})),
        response("r3", SimpleNamespace(type="message")),
    ])
    client = SimpleNamespace(responses=responses)
    ctx = ToolContext()
    request = {"model": "m", "instructions": "i", "input": "Triage 1043", "tools": TOOL_SCHEMAS}

    final = asyncio.run(run_responses_with_tools(
        client,
        request_args=request,
        execute_function=lambda name, args: execute_tool(name, args, ctx, load_bank_data()),
    ))

    assert final.id == "r3"
    assert [c["tool"] for c in ctx.calls] == ["get_alert", "get_policy", "compute_risk_indicators"]
    first, second, third = responses.requests
    assert first["input"] == "Triage 1043" and "previous_response_id" not in first
    assert second["previous_response_id"] == "r1" and third["previous_response_id"] == "r2"
    assert second["instructions"] == "i" and second["tools"] is TOOL_SCHEMAS
    outputs = second["input"]
    assert [o["call_id"] for o in outputs] == ["c1", "c2"]
    assert json.loads(outputs[0]["output"])["alert_id"] == "ALR-2026-1043"


def test_loop_stops_after_max_rounds():
    endless = [response(f"r{i}", call(f"c{i}", "get_policy", {"query": "POL-01"})) for i in range(5)]
    client = SimpleNamespace(responses=FakeResponses(endless))
    final = asyncio.run(run_responses_with_tools(
        client,
        request_args={"model": "m", "input": "x"},
        execute_function=lambda name, args: {"ok": True},
        max_rounds=2,
    ))
    assert final.id == "r2"
    assert function_calls(final)


def test_loop_returns_immediately_without_function_calls():
    client = SimpleNamespace(responses=FakeResponses([response("only", SimpleNamespace(type="mcp_call"))]))
    final = asyncio.run(run_responses_with_tools(client, request_args={"input": "hi"}, execute_function=lambda n, a: {}))
    assert final.id == "only" and len(client.responses.requests) == 1


def test_loop_awaits_async_tool_results():
    client = SimpleNamespace(responses=FakeResponses([
        response("r1", call("c1", "search_past_answers", {"question": "q"})),
        response("r2", SimpleNamespace(type="message")),
    ]))

    async def execute(name, args):
        return {"tool": name, "async": True}

    final = asyncio.run(run_responses_with_tools(client, request_args={"input": "x"}, execute_function=execute))
    assert final.id == "r2"
    assert json.loads(client.responses.requests[1]["input"][0]["output"]) == {"tool": "search_past_answers", "async": True}
