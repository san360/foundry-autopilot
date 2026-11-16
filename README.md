# Foundry Autopilot – FSI demo: "Hire a FinCrime analyst"

A production-shaped demo of **Microsoft Foundry autopilots** for financial services. Contoso Bank's Financial Crime Operations team **hires an AI autopilot** that works in Teams and email **under its own Microsoft Entra identity** (agent user account with mailbox, Teams presence and a manager). It triages AML, sanctions and KYC alerts with exact, deterministic figures, refuses what it must refuse (tipping-off, closing alerts, prompt injection), sees only its own team's data, and can be stopped by anyone close to the work.

> **Preview:** Foundry autopilots are in public preview through the Microsoft **Frontier** program (no SLA). All bank data here is **synthetic**. Nothing in this repository is legal or compliance advice.

## Documentation

| # | Document | Answers |
|---|---|---|
| 01 | [What is a Foundry autopilot?](docs/01-what-is-foundry-autopilot.md) | Definition, how it differs from prompt / hosted / workflow agents and from assistive / background agents, blueprint → instances, Agent 365 and Copilot "Autopilot" |
| 02 | [Prerequisites, licensing and roles](docs/02-prerequisites-and-licensing.md) | Frontier enrollment, **how many licences the demo needs**, preview vs GA per-user licensing, Azure and Microsoft 365 roles, regions, readiness of the demo tenants (Zava, MCAPS) |
| 03 | [Identity, security and governance](docs/03-identity-and-governance.md) | Entra objects, runtime token flow, consent vs access, kill switches, Purview/Defender, bank regulatory talking points |
| 04 | [Architecture and components](docs/04-architecture-and-components.md) + [architecture.drawio](docs/architecture.drawio) | **Services at a glance** (used and not used, with billing); every Azure, Entra and Microsoft 365 component; flows; configuration; changes vs the official sample |
| 05 | [Cost model](docs/05-cost-model.md) | Live Sweden Central prices, **measured cost per triage (≈ USD 0.018 model)**, monthly scenarios, cost levers |
| 06 | [Use cases](docs/06-use-cases.md) | When to use an autopilot, FSI candidates, why AML triage, the six synthetic alert scenarios |
| 07 | [FSI demo storyline](docs/07-fsi-demo-storyline.md) + [demo prompts](demo/demo-prompts.md) | 25-minute run of show, cast, talk track, tough questions |
| 08 | [Deployment runbook](docs/08-deployment-runbook.md) | Exact steps (automated and human), troubleshooting, teardown order |
| 09 | [Resources](docs/09-resources.md) | Official docs, announcements, videos, GitHub repos (verified) |
| 10 | [Learning guide](docs/10-learning-guide.md) | **Start here to learn the solution**: the use case, blueprint → instances, what exists live, the runtime flows, the token exchange (T1 → T2 → agent user), every permission granted and why, kill switches, a self-check quiz |
| 11 | [Customer demo pitch](docs/11-customer-demo-pitch.md) | **§0: the value story across both autopilots** (why an autopilot, not Copilot; what FinCrime and the Bid Desk each prove), then the customer-facing story and a 20-minute **one-person** run of show for the Zava tenant: talk track, proof points, fallbacks, objection handling, cost, pilot proposal |
| 12 | [RFP Bid Desk](docs/12-rfp-bid-desk.md) | A second autopilot from the same image: **per-instance identity enforced by Azure** (each bid team's instance reads only its own Azure AI Search index), three per-instance token flows, the **token inspector** (`/whoami` in every channel, KQL), deploy steps and a 12-minute run of show |
| 13 | [Identity analogy, hiring steps and permissions](docs/13-identity-analogy-and-hiring.md) + drawio pages *Analogy*, *Hiring steps & permissions*, *RFP Bid Desk* | **Blueprint vs agent identity vs agent user explained with a badge-office analogy**, prerequisites, the seven steps from zero to a working instance with the role that runs each, which permission lands where, and the three hiring paths compared |
| 14 | [Agent policy templates](docs/14-agent-policy-templates.md) | **Which policy template to pick when approving an agent**: every option in *Security policies and protections* with licence and preview status, the Entra, Purview, SharePoint, Teams and Defender layers next to it, a decision guide per scenario and three ready-made templates for this repo |
| 15 | [Custom MCP server behind an AI gateway](docs/15-mcp-behind-ai-gateway.md) + [samples](samples/mcp-behind-ai-gateway/) | **Can an autopilot call your own MCP server behind API Management that checks token claims?** Yes: which token (agent identity, agent user, OBO), which claims (`roles`, `scp`, `azp`, `xms_sub_fct`), **where to assign app roles** (agent identity per instance, blueprint with inheritance, agent user), a sample APIM policy, per-instance isolation, alternatives and limits |
| 16 | [Voice, meetings and avatars](docs/16-voice-and-meetings.md) + [demo script](docs/16a-voice-meeting-demo-script.md) | **Can an instance join a Teams meeting or call, listen, speak and act?** Plain-language text-versus-audio explainer; an instance gets chat, events and transcripts (Work IQ, live from Nov 2026), but **no documented way for the agent user to join call audio**. Voice today: call a **Foundry voice agent on a Teams Phone number** (preview, hosted agent as subagent or conversation engine); in-meeting voice and **avatars** only through a separate ACS or media-bot participant (DIY). Options matrix with identity and per-instance data boundary, recommendation, roadmap, tenant checklist |
| 17 | [Agents collaborating in a Teams meeting](docs/17-agents-collaborating-in-meetings.md) | **Can two hired instances work together in a meeting chat?** Yes, verified live: BankingBids @mentions PublicSectorBids, which answers from its own library for the bid manager to approve (**ask, don't access**: Azure still returns 403 across teams). Delivery verdict vs the documented "no bot-to-bot" rule, loop prevention, sharing policy, audit, 10-minute run of show |
| 18 | [Governance gaps](docs/18-governance-gaps.md) | **What the platform enforces, what code enforces, what's missing** for autopilots in a regulated bank: 15 gaps with evidence (observed in Zava or documented on Learn), severity, owner and mitigation; **restricting who can use an instance** (out-of-the-box options and the sample's `/access` allowlist); a control map and a now / next / watch roadmap |
| 19 | [Private networking and Teams / Copilot channel security](docs/19-private-networking-and-channel-security.md) | **Can a private-endpoint-only Foundry still serve Teams and Copilot, and where do you secure it?** Only through a Foundry-managed, source-IP-filtered public Activity Protocol route (no Private Link for Microsoft 365 channels; autopilot support for this path undocumented). Protocol trace, Bot Service roles (Microsoft-managed vs customer-owned), why App Gateway / APIM / Front Door can't sit in the native route, firewall allowlist matrix with unverified paths flagged, identity and tool governance, validation plan, open questions |

## Status (2026-10-31)

Deployed to the **Zava demo tenant** `diax07991363.onmicrosoft.com` (`5b26daf8-…`), subscription `ME-DIAx07991363-skomma-1` (shared with other teams' autopilots), azd environment `fsifincrime03`. The tenant is already enrolled in Frontier. The earlier deployment `fsifincrime02` in the E7 MCAPS tenant **MngEnvMCAP809970** still exists, waiting for Frontier enrollment there; the first one, in MngEnvMCAP283191, was torn down on 2026-10-27.

| Step | Status |
|---|---|
| Azure resources (`rg-fsi-autopilot`, Sweden Central): Foundry account and project, `gpt-6.1-sol`, ACR, Toolbox, App Insights | ✅ Deployed |
| Hosted agent `fsifincrime03-fincrime-autopilot` (version 5 serves all traffic, `digital_worker_type: m365`) + Entra agent identity blueprint | ✅ Active |
| Published to Microsoft 365 as an **autopilot blueprint** ("FinCrime Alert Triage", Teams app `938ebfab-…`) | ✅ Published (re-publish on each rollout shows *pending* again; instances keep working) |
| Unit tests (144) · smoke test with two live scenarios · full live scenario evaluation against the deployed model | ✅ Passing |
| **Frontier**: 25-seat Frontier subscription (`MICROSOFT_AGENT_365_TIER_3`, trial until 2026-11-28). Each seat brings Teams, Exchange and OneDrive for the agent user | ✅ Already in place |
| **Hired** MiraRetail and TheoCorporate: first with the Entra Agent ID APIs, then **rehired in the Microsoft 365 admin center** on 2026-11-01 so they appear in Agent 365 (agent-user IDs mapped in `SEGMENT_SCOPE_RULES`) | ✅ Done |
| End-to-end: MiraRetail answers in Teams and replies to a `[TM ALERT]` email with a triage memo (ESCALATE TO L2, High 85/100) | ✅ Verified |
| **RFP Bid Desk** ([doc 12](docs/12-rfp-bid-desk.md)): hosted agent `fsifincrime03-rfp-bid-desk` (version 7), Azure AI Search in North Europe. **BankingBids** and **PublicSectorBids** were first created with the Entra APIs, then **re-hired in the Microsoft 365 admin center on 2026-11-02** so they appear under the agent's Instances; `sync-bid-desk-instances.ps1` mapped their IDs and gave each Search Index Data Reader on its own index only | ✅ Verified 2026-11-01 (`/whoami probe` 200 own / 403 other / 403 container, recall, isolation, email intake, group chat) and 2026-11-02 (daily-check reminder). Re-test after the re-hire: ⏳ |
| Create the team chats and run the [demo](docs/07-fsi-demo-storyline.md) | ⏳ Human steps ([runbook](docs/08-deployment-runbook.md) §6–7) |

## Quickstart

```powershell
az login --tenant <tenant-id>; az account set --subscription <subscription-id>
pwsh ./scripts/preflight.ps1 -SubscriptionId <subscription-id> -Location swedencentral
azd env new <name> --subscription <subscription-id> --location swedencentral
azd env set AZURE_RESOURCE_GROUP <rg>; azd env set ALLOWED_SENDER_DOMAINS <tenant-domain>
azd provision                     # infra + Toolbox + ACR build + hosted agent version + publish as autopilot
pwsh ./scripts/smoke-test.ps1 -RunEval
```

Then: approve in the [Microsoft 365 admin center](https://admin.cloud.microsoft/?#/agents/all/requested) → hire in Teams (**Apps > Agents for your team > Create instance**) → run the [demo](docs/07-fsi-demo-storyline.md).

## How it works (one paragraph)

The container is the official Foundry autopilot sample's Microsoft 365 Agents SDK host (activity protocol, Agent 365 notifications, per-turn agentic-user token for the Mail/Teams/Word/Excel/SharePoint/Calendar MCP servers) with a new **FinCrime brain**: instructions with a strict memo format and rules; a Responses API **tool loop** over **seven read-only function tools** (alerts, KYC profile, transactions, sanctions/PEP screening, deterministic risk indicators, policy lookup) on synthetic data; and code-level **guardrails** (sender-domain and tenant checks, `NO_REPLY` in group chats, tipping-off detector, prompt-injection flags, per-instance segment entitlement). There is **no tool** to close alerts, release payments or file SARs: humans decide.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q                                      # 144 unit tests (tools, guardrails, loop, RFP Bid Desk, token inspector)
.\.venv\Scripts\python.exe eval\run_scenarios.py --endpoint <project endpoint> --subscription <subscription-id>  # 13 live scenarios, ~USD 0.15
pwsh ./scripts/smoke-test.ps1                                                 # deployed-state checks
```

Latest live run: [eval/results](eval/results) (2026-10-31, Zava deployment, 13/13 passed: triage outcomes, tipping-off and close-request refusals, cross-team access denial, `NO_REPLY`, prompt-injection flagging, Prompt Shields block, email-triggered HTML memo).

## Repository layout

```text
azure.yaml, infra/          azd + Bicep (Foundry account/project, model, ACR, monitoring, RBAC; private-network variant)
scripts/                    post-provision pipeline (Toolbox, ACR build, agent version, session retirement, publish), preflight, smoke test, instance creation via the Entra APIs, teardown
src/fincrime_autopilot/     hosted agent: host, agent, prompts, tool loop, FSI tools, guardrails, synthetic data; RFP Bid Desk scenario (AUTOPILOT_SCENARIO=rfp), per-instance tokens, token inspector
tests/                      unit tests            eval/  live scenario suite and results
demo/                       alert email sender, persona setup, copy-paste prompts, customer pitch deck (PowerPoint); rfp/ synthetic RFP and per-team answer libraries, send-rfp and send-bid-reminder
docs/                       documentation 01–19 and architecture.drawio (6 pages)
```

## Credits

Built on [microsoft-foundry/foundry-samples – `samples/python/foundry-autopilot-agent`](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/foundry-autopilot-agent) (MIT). Field lessons from [aiappsgbb/foundry-autopilots](https://github.com/aiappsgbb/foundry-autopilots).
