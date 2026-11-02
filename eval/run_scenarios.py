"""Live scenario evaluation for the FinCrime autopilot brain.

Runs the agent's real instructions, FSI function tools and Responses API tool
loop against a Foundry model deployment and checks each scenario's expected
behaviour. The Microsoft 365 MCP servers are not used here: they need the
agentic-user token that only exists inside a hired autopilot instance, so
end-to-end Microsoft 365 behaviour is verified in Teams (see docs/08).

Usage (from the repository root, after `azd provision`):
    python eval/run_scenarios.py --endpoint <project endpoint> --model gpt-6.1-sol
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azure.ai.projects.aio import AIProjectClient  # noqa: E402
from azure.identity.aio import AzureCliCredential  # noqa: E402

from fincrime_autopilot.fsi_data import load_bank_data  # noqa: E402
from fincrime_autopilot.fsi_tools import TOOL_SCHEMAS, ToolContext, execute_tool  # noqa: E402
from fincrime_autopilot.guardrails import detect_tipping_off_request, resolve_allowed_segments  # noqa: E402
from fincrime_autopilot.prompts import CONTENT_FILTER_MESSAGE, TIPPING_OFF_NOTICE, build_instructions, is_content_filter_error  # noqa: E402
from fincrime_autopilot.tool_loop import function_calls, run_responses_with_tools  # noqa: E402


class RecordingResponses:
    """Wraps ``client.responses`` to accumulate token usage across tool rounds."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0
        self.input_tokens = 0
        self.cached_tokens = 0
        self.output_tokens = 0
        self.reasoning_tokens = 0

    async def create(self, **kwargs: Any) -> Any:
        response = await self._inner.create(**kwargs)
        self.calls += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
            details = getattr(usage, "input_tokens_details", None)
            self.cached_tokens += getattr(details, "cached_tokens", 0) or 0
            out_details = getattr(usage, "output_tokens_details", None)
            self.reasoning_tokens += getattr(out_details, "reasoning_tokens", 0) or 0
        return response


class RecordingClient:
    def __init__(self, inner: Any) -> None:
        self.responses = RecordingResponses(inner.responses)


async def run_scenario(openai_client: Any, model: str, scenario: dict[str, Any], prices: dict[str, float]) -> dict[str, Any]:
    data = load_bank_data()
    ctx = ToolContext(allowed_segments=resolve_allowed_segments([scenario["instance"]]), instance_label=scenario["instance"])
    instructions = build_instructions(
        scenario["instance"].split(" (")[0], "Jonas Weber (L1 analyst)", ctx.scope_label(), channel=scenario["channel"]
    )
    text = scenario["input"]
    if detect_tipping_off_request(text):
        text = TIPPING_OFF_NOTICE + text
    client = RecordingClient(openai_client)
    started = time.perf_counter()
    error = None
    output = ""
    blocked = False
    try:
        response = await run_responses_with_tools(
            client,
            request_args={"model": model, "instructions": instructions, "input": text, "tools": TOOL_SCHEMAS},
            execute_function=lambda name, args: execute_tool(name, args, ctx, data),
            max_rounds=8,
        )
        output = "" if function_calls(response) else (response.output_text or "")
    except Exception as ex:  # noqa: BLE001 - report, don't abort the suite
        if is_content_filter_error(ex):
            # Same behaviour as the agent: Prompt Shields / content filter blocked the request.
            blocked = True
            output = CONTENT_FILTER_MESSAGE
        else:
            error = f"{type(ex).__name__}: {ex}"
    elapsed = round(time.perf_counter() - started, 1)

    tools_used = [c["tool"] for c in ctx.calls]
    failures = []
    if error:
        failures.append(error)
    if blocked and not scenario.get("accept_content_filter"):
        failures.append("blocked by content filter (not expected for this scenario)")
    for tool in ([] if blocked else scenario.get("expect_tools", [])):
        if tool not in tools_used:
            failures.append(f"expected tool not called: {tool}")
    for pattern in ([] if blocked else scenario.get("must_match", [])):
        if not re.search(pattern, output, re.M):
            failures.append(f"missing: /{pattern}/")
    for pattern in scenario.get("must_not_match", []):
        if re.search(pattern, output, re.M):
            failures.append(f"forbidden: /{pattern}/")

    usage = client.responses
    uncached = max(usage.input_tokens - usage.cached_tokens, 0)
    cost = (uncached * prices["input"] + usage.cached_tokens * prices["cached"] + usage.output_tokens * prices["output"]) / 1_000_000
    return {
        "id": scenario["id"],
        "instance": scenario["instance"],
        "passed": not failures,
        "failures": failures,
        "blocked_by_content_filter": blocked,
        "tools_used": tools_used,
        "model_calls": usage.calls,
        "latency_s": elapsed,
        "input_tokens": usage.input_tokens,
        "cached_tokens": usage.cached_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "estimated_cost_usd": round(cost, 5),
        "output": output,
    }


def write_reports(results: list[dict[str, Any]], model: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    # Build names explicitly: Path.with_suffix() would treat ".1-sol" in "gpt-6.1-sol" as an extension.
    json_path = out_dir / f"{stamp}-{model}.json"
    md_path = out_dir / f"{stamp}-{model}.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    passed = sum(r["passed"] for r in results)
    lines = [
        f"# Scenario evaluation - {model} - {stamp} UTC",
        "",
        f"**{passed}/{len(results)} scenarios passed.**",
        "",
        "| Scenario | Result | Tools used | Model calls | Latency (s) | Input / cached / output tokens | Est. cost (USD) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        status = "PASS" if r["passed"] else "FAIL: " + "; ".join(r["failures"])[:160]
        if r.get("blocked_by_content_filter"):
            status += " (blocked by Prompt Shields / content filter)"
        lines.append(
            f"| {r['id']} | {status} | {', '.join(r['tools_used']) or '-'} | {r['model_calls']} | {r['latency_s']} | "
            f"{r['input_tokens']} / {r['cached_tokens']} / {r['output_tokens']} | {r['estimated_cost_usd']} |"
        )
    total_cost = sum(r["estimated_cost_usd"] for r in results)
    lines += ["", f"Total estimated model cost for this run: **USD {total_cost:.4f}**", ""]
    for r in results:
        lines += [f"## {r['id']} ({'PASS' if r['passed'] else 'FAIL'})", "", "```text", r["output"].strip()[:4000], "```", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", default=os.getenv("AZURE_AI_PROJECT_ENDPOINT"))
    parser.add_argument("--model", default=os.getenv("MODEL_NAME", "gpt-6.1-sol"))
    parser.add_argument(
        "--subscription",
        default=os.getenv("AZURE_SUBSCRIPTION_ID") or os.getenv("SUBSCRIPTION_ID"),
        help="Azure subscription of the Foundry project. Binds the az CLI token to it, so a different "
        "az default subscription (or a guest identity in the tenant) is never used.",
    )
    parser.add_argument("--only", nargs="*", help="Scenario IDs to run")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--price-input", type=float, default=2.0, help="USD per 1M uncached input tokens")
    parser.add_argument("--price-cached", type=float, default=0.10, help="USD per 1M cached input tokens")
    parser.add_argument("--price-output", type=float, default=10.0, help="USD per 1M output tokens")
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("--endpoint or AZURE_AI_PROJECT_ENDPOINT is required")

    scenarios = json.loads((ROOT / "eval" / "scenarios.json").read_text(encoding="utf-8"))
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in set(args.only)]
    prices = {"input": args.price_input, "cached": args.price_cached, "output": args.price_output}

    async with AzureCliCredential(subscription=args.subscription) as credential:
        async with AIProjectClient(endpoint=args.endpoint, credential=credential) as project:
            openai_client = project.get_openai_client()
            semaphore = asyncio.Semaphore(max(1, args.concurrency))

            async def guarded(scenario: dict[str, Any]) -> dict[str, Any]:
                async with semaphore:
                    result = await run_scenario(openai_client, args.model, scenario, prices)
                    print(f"[{'PASS' if result['passed'] else 'FAIL'}] {result['id']} ({result['latency_s']}s, tools={result['tools_used']})"
                          + ("" if result["passed"] else f" -> {result['failures']}"), flush=True)
                    return result

            results = await asyncio.gather(*(guarded(s) for s in scenarios))
            await openai_client.close()

    report = write_reports(list(results), args.model, ROOT / "eval" / "results")
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed. Report: {report}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
