# 05 · Cost model

All prices are **Azure retail list prices in USD for Sweden Central, retrieved on 2026-10-26** from the public Azure Retail Prices API (`prices.azure.com`), unless stated otherwise. Your agreement prices may differ. Re-run the queries in [§6](#6-re-check-prices-yourself) before quoting.

## 1. What you pay for

| Component | Meter | Unit price | Charged when |
|---|---|---|---|
| **Model**: `gpt-6.1-sol`, Global Standard, short context | Input / **cached input** / output tokens | **USD 2.00 / 0.10 / 10.00 per 1M tokens** | Per call (pay-as-you-go, no idle cost) |
| Alternative models | `gpt-5.4-mini`: 0.75 / 0.075 / 4.50 · `gpt-chat-latest`: 5.00 / 0.50 / 30.00 · `gpt-6-astra`: 10.00 / 1.00 / 50.00 | per 1M tokens | |
| **Hosted agent compute** | Foundry Agents "Hosted vCPU Usage" / "Hosted Memory Usage" | **USD 0.10934 per vCPU-hour / 0.01298 per GiB-hour** | While a session sandbox is alive; scales to zero when idle |
| Container registry | ACR Basic | USD 0.1666 per day (about USD 5 per month), storage USD 0.10 per GB-month above the included amount | Always |
| Monitoring | Log Analytics ingestion (Analytics Logs) | USD 2.99 per GB (first 5 GB per billing account per month free); retention USD 0.13 per GB-month beyond the included 31 days | Per GB ingested |
| Web search tool (Toolbox) | Reference: "Grounding with Bing Search" | USD 14 per 1,000 transactions | Only when the model searches the web |
| Code interpreter (Toolbox) | Foundry tool meter | See the [Foundry Agent Service pricing page](https://azure.microsoft.com/pricing/details/ai-foundry/) (no retail API meter found) | Only when used |
| Foundry account, project, agent definitions, Toolbox definition | n/a | No standing charge | n/a |
| **Agent 365 / Microsoft 365** | Licences | Preview: **Frontier seats are free** (25 per tenant). GA: **USD 15 per user per month** (Agent 365) or included in **Microsoft 365 E7 (USD 99)**, per *human* user; agents and instances are not licensed | Monthly |

## 2. Measured model cost per turn (this demo)

From `eval/results/20261026-120546-gpt-6.1-sol` (13 scenarios, real model, FSI function tools, no Microsoft 365 tools):

| Turn type | Model calls | Input tokens (cached) | Output tokens | Latency | **Model cost** |
|---|---|---|---|---|---|
| Full alert triage (average of 9 triage-style scenarios) | 3–4 | 11,924 (7,798 = **65% cached**) | 918 | 28 s | **USD 0.018** |
| Email-triggered triage (ALR-2026-1045) | 4 | 15,242 (9,427) | 1,136 | 31 s | USD 0.024 |
| Short chat turn (queue, refusal, scope denial, `NO_REPLY`) | 1–2 | 1,500–3,600 (mostly cached) | 6–204 | 2–12 s | **USD 0.0015** |
| Whole 13-scenario evaluation run | 37 | n/a | n/a | about 1 min with concurrency 3 | **USD 0.15** |

In Teams and email, each call also carries the Microsoft 365 MCP and Toolbox tool definitions. **Plan for about USD 0.03–0.04 per triage in production** (roughly 1.5–2× the measured figure), and validate with Application Insights once instances are live.

## 3. How hosted compute is billed (and why it is cheap here)

* Container size in this repo: **1 vCPU + 2 GiB**, so USD 0.10934 + 2 × 0.01298 = **USD 0.135 per active hour**. The upstream sample uses 2 vCPU / 4 GiB (USD 0.27 per hour).
* Sandboxes scale to zero when idle. An earlier billing measurement found usage billed in **≈20.6-minute windows**: requests inside a warm window add no compute cost, while requests spread across many windows pay for each window. That figure was **measured, not published by Microsoft**; re-derive it before relying on it.
* So one window costs about USD 0.135 × 0.343 h = **USD 0.046**. A demo afternoon costs well under USD 1 of compute; a business day of steady traffic is at most about USD 1.35 per always-warm sandbox.

## 4. Monthly scenarios

| Scenario | Assumptions | Model | Compute | ACR | Monitoring | Web search | **Azure total / month** | Licences |
|---|---|---|---|---|---|---|---|---|
| **Demo environment** | 3 demos plus rehearsals, about 300 triages and 300 chat turns, about 30 compute windows | USD 11 | USD 1.4 | USD 5 | ≈ USD 0 (free tier) | < USD 1 | **≈ USD 18** | USD 0 (Frontier preview) |
| **Pilot**: one FinCrime team, 2 instances | 2,000 triages and 3,000 chat turns; worst case 2 sandboxes warm 10 h × 22 days | USD 75 | ≤ USD 60 | USD 5 | ≈ USD 5–10 | ≈ USD 5 | **≈ USD 150** | GA: 10 users × USD 15 = USD 150, or USD 0 extra if already on E7 |
| **Scale**: 5 teams, 10 instances | 20,000 triages and 30,000 chat turns | ≈ USD 750 | ≤ USD 300 | USD 5 | ≈ USD 30 | ≈ USD 30 | **≈ USD 1,100** | Per human user (managers, analysts, sponsors) |

**Value framing (illustrative assumptions, not a quote):** if an L1 analyst spends about 20 minutes collecting facts per alert and the autopilot removes about 15 of them, 2,000 alerts per month frees about 500 analyst hours. At a fully loaded EUR 60 per hour that is about EUR 30,000 per month, against about USD 150 of Azure consumption plus licences. Validate with the bank's own time-and-motion data during a pilot.

## 5. Cost levers

| Lever | Effect |
|---|---|
| Model choice | `gpt-5.4-mini` is about 2.7× cheaper than `gpt-6.1-sol` but must pass the scenario suite first; `gpt-6-astra` is 5× more expensive (re-run `eval/run_scenarios.py` after any change) |
| Prompt caching | Cached input costs 1/20 of uncached; stable instructions and tool schemas reach about 65% cache hits |
| Tool discipline | The instructions cap counterparty screening at three. That cut the email triage from 12 screening calls and 48 s to 1 call and 31 s |
| `MAX_TOOL_ROUNDS` | Upper bound on model calls per turn (default 8) |
| Container size | 1 vCPU / 2 GiB is enough (the agent is I/O-bound); it multiplies every compute window |
| Batch work in time | Fewer, denser compute windows (for example process the alert queue in bursts) |
| Telemetry | Message content capture off by default; 30-day retention |
| Turn it off | `azd down` removes all Azure cost. **Delete hired instances in the Microsoft 365 admin center first**: Azure teardown does not remove agent users, mailboxes or seats |

## 6. Re-check prices yourself

```powershell
# Hosted agent compute (Foundry Agents)
Invoke-RestMethod "https://prices.azure.com/api/retail/prices?`$filter=serviceName eq 'Foundry Tools' and armRegionName eq 'swedencentral' and productName eq 'Foundry Agents'" |
  Select-Object -ExpandProperty Items | Select-Object meterName, unitOfMeasure, retailPrice

# Model tokens (example: gpt-6.1-sol)
Invoke-RestMethod "https://prices.azure.com/api/retail/prices?`$filter=serviceName eq 'Foundry Models' and armRegionName eq 'swedencentral' and contains(meterName,'6.1-sol')" |
  Select-Object -ExpandProperty Items | Select-Object meterName, unitOfMeasure, retailPrice
```

Licensing sources: [Microsoft Agent 365 licensing FAQ](https://www.microsoft.com/licensing/faqs/122), [Agent 365 Frontier](https://learn.microsoft.com/microsoft-agent-365/frontier).
