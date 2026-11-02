# 09 · Resources: docs, samples, videos and blogs

Compiled 2026-10-26. Every link below was opened and checked during research; items that could not be verified are marked. Autopilots launched in June 2026, so community content is still thin. **No video or conference session with "autopilot" in its title was found**; the videos listed cover the building blocks (hosted agents, Entra Agent ID, Agent 365).

## 1. Official documentation (start here)

| Document | What you get |
|---|---|
| [What is an autopilot in Microsoft Foundry?](https://learn.microsoft.com/azure/foundry/agents/concepts/autopilot-overview) | Definition, identity model, assistive vs background vs autopilot, blueprints, patterns |
| [Autopilot lifecycle in Microsoft Foundry](https://learn.microsoft.com/azure/foundry/agents/concepts/autopilot-lifecycle) | Stages, roles (Azure admin, developer, tenant admin, manager, access manager), onboarding settings, governance |
| [Quickstart: Build your first autopilot](https://learn.microsoft.com/azure/foundry/agents/how-to/agent-365) | Prerequisites, permissions, `azd provision`, publish API, approval wizard, hiring, troubleshooting |
| [Microsoft Agent 365 integration with Foundry](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-365-integration) | Registry sync, autopilot publishing, data collection, data residency |
| [Hosted agents](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents) and [hosted agent permissions](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions) | Runtime, regions, RBAC |
| [Preview Agent 365 features through the Frontier program](https://learn.microsoft.com/microsoft-agent-365/frontier) | Enrollment steps, 25 Frontier seats, FAQ |
| [Discover, create and onboard agents with their own identity](https://learn.microsoft.com/microsoft-agent-365/onboard) | User flow: Agents for your team → Request / Create instance → configure name, alias, domain |
| [Create agentic user instances on behalf of managers](https://learn.microsoft.com/microsoft-agent-365/admin/create-agentic-user-instances) | Admin flow: Registry → Create instance wizard (manager, licence validation, customization, review) |
| [Agent 365 overview](https://learn.microsoft.com/microsoft-agent-365/overview), [Publish agent to Microsoft admin center](https://learn.microsoft.com/microsoft-agent-365/developer/publish), [Agent 365 tooling servers](https://learn.microsoft.com/microsoft-agent-365/tooling-servers-overview) | Control plane, publishing, Microsoft 365 MCP servers |
| [Microsoft Entra Agent ID: agent identities](https://learn.microsoft.com/entra/agent-id/what-are-agent-identities), [agent users](https://learn.microsoft.com/entra/agent-id/agent-users) | Identity objects behind autopilots |
| [Microsoft Agent 365 licensing FAQ](https://www.microsoft.com/licensing/faqs/122) | Per-user licensing, USD 15 standalone, USD 99 E7, what is free vs premium |
| [Agent management roles and permissions in the Microsoft 365 admin center](https://learn.microsoft.com/microsoft-agent-365/admin/agent-roles-perms) | Which Entra roles can view the registry vs approve and manage agents (Global/AI Administrator vs Global/AI Reader) |
| [Transition Copilot Studio and Foundry agent security to Agent 365](https://learn.microsoft.com/defender-xdr/security-for-ai/transition-agent-security-to-agent-365) | Defender / security-for-AI changes |

## 2. Announcements and blogs

| Date | Source | Key points |
|---|---|---|
| 18 Nov 2025 | [Microsoft Agent 365: the control plane for AI agents](https://www.microsoft.com/en-us/copilot/blog/2025/11/18/microsoft-agent-365-the-control-plane-for-ai-agents/) | Launch of Agent 365: registry, access control, visualization, interoperability, security |
| 18–19 Nov 2025 | [From innovation to enterprise trust with Agent 365](https://devblogs.microsoft.com/microsoft365dev/from-innovation-to-enterprise-trust-with-microsoft-agent-365/), [Agent 365 interoperability](https://devblogs.microsoft.com/microsoft365dev/microsoft-agent-365-interoperability-for-smart-secure-productivity/) | Entra Agent ID foundation; notifications and Microsoft 365 MCP servers in preview |
| 1 May 2026 | [Agent 365 blog hub (Tech Community)](https://techcommunity.microsoft.com/category/microsoft365/blog/agent-365-blog) | Agent 365 general availability; monthly "What's new" posts |
| 2 Jun 2026 | [Foundry Agent Service at Build 2026](https://devblogs.microsoft.com/foundry/agent-service-build2026/) | "Microsoft Agent Platform": build, deploy, operate |
| 3 Jun 2026 | [From building agents to working with them: enterprise agent distribution](https://devblogs.microsoft.com/foundry/from-building-agents-to-working-with-them-enterprise-agent-distribution-in-microsoft-foundry/) | **Autopilot agents in public preview**; publish to Microsoft 365 and Teams; every agent auto-registered in Agent 365; Workstream Manager sample |
| 7 Jul 2026 | [What's new in Microsoft Foundry, June 2026](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-june-2026/) | Publish-to-Teams GA; autopilot preview details |
| 15 Oct 2026 | [What's new in Microsoft Foundry, September 2026](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-september-2026/) | Routines, tool search, A2A GA; **no autopilot GA announced** |
| 25 Sep 2026 | [Introducing the new Copilot with Home, Code and Autopilot](https://blogs.microsoft.com/blog/2026/09/25/introducing-the-new-copilot-with-home-code-and-autopilot/) (Jared Spataro) | End-user **Autopilot** (formerly Scout) in the Copilot app; private preview end of Sep 2026 |
| 28 Sep 2026 | [Bank on intelligence: building the financial institution of the agentic era](https://www.microsoft.com/en-us/microsoft-cloud/blog/financial-services/banking/2026/09/28/bank-on-intelligence-building-the-financial-institution-of-the-agentic-era/) | Microsoft's FSI framing: "human-led and agent-operated" |
| n/a | [candede.com: Agent 365 and Entra Agent ID deep dive](https://www.candede.com/articles/microsoft-agent-365-and-entra-agent-id/) | Independent technical walkthrough (community) |

## 3. Videos and sessions

| Title | Channel / event | Notes |
|---|---|---|
| [Microsoft Foundry – AI app and agent factory](https://www.youtube.com/watch?v=C6rxEGJay70) | Microsoft Mechanics (Dec 2025) | Portal tour: build, evaluate, publish |
| [Foundry Agent Service + Microsoft Agent Framework explained](https://www.youtube.com/watch?v=iR7_57lJOz8) | Microsoft Mechanics | Hosted agents, Entra identity per agent |
| [Microsoft Entra Agent ID explained](https://www.youtube.com/watch?v=N-B-kD28P2I) | Microsoft Mechanics | The identity construct behind autopilots |
| [Introducing Microsoft Agent 365 (BRK306)](https://www.youtube.com/watch?v=-LSrJtikrh8) | Microsoft Ignite 2025 | Agent 365 control plane (catalog code now reused for 2026, so abstract not re-verifiable) |
| [Secure access for AI agents with Microsoft Entra (BRK265)](https://www.youtube.com/watch?v=rBRwT0E0jQA) | Microsoft Ignite 2025 | Agent identity security |
| [Agent 365 and Agent ID overview](https://www.youtube.com/live/WTcyL68qTo8) | John Savill's Technical Training | Independent deep dive |
| [From prototype to production: build and run agents at scale (BRK241)](https://build.microsoft.com/en-US/sessions/BRK241) | Build 2026 | Hosted deployment with identity, networking, evals |
| [Claw and agent harness in Microsoft Foundry (BRK243)](https://build.microsoft.com/en-US/sessions/BRK243) | Build 2026 | Long-running agents, triggers, state; Copilot SDK harness |
| [From zero to teammate in 25 minutes: build a Teams agent live (DEM332)](https://build.microsoft.com/en-US/sessions/DEM332) | Build 2026 | Teams agent colleagues can @mention and delegate to |
| [Build agents where work happens (DEM334)](https://build.microsoft.com/en-US/sessions/DEM334) | Build 2026 | Teams SDK chats, channels, meetings (listed, not re-fetched) |

## 4. GitHub repositories

### Directly autopilot-related

| Repository | Owner | Why it matters |
|---|---|---|
| [microsoft-foundry/foundry-samples – `samples/python/foundry-autopilot-agent`](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/foundry-autopilot-agent) and [C#](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/csharp/foundry-autopilot-agent) | Microsoft | **The sample the quickstart uses, and the base of this repository.** azd provision → Toolbox → ACR build → hosted agent → publish as autopilot. Includes a private-networking variant |
| [microsoft-foundry/foundry-samples – `samples/python/autopilot-agents`](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/autopilot-agents) (`hello-world`, `foundry-toolbox`, `meeting-assistant`) | Microsoft | Newer azd-native style: `host: azure.ai.agent`, direct code deploy (no Docker/ACR), `azd ai agent publish`, Foundry AgentServer Activity SDK with `digital_worker=True`. Requires azd extension `azure.ai.agents` ≥ 1.0.0-beta.16 |
| [microsoft/frontiertour27-BRK240-building-context-aware-agents-with-microsoft-iq](https://github.com/microsoft/frontiertour27-BRK240-building-context-aware-agents-with-microsoft-iq) | Microsoft (event repo) | Industry-flavoured Agent 365 autopilot (pharma supplier assurance) grounded in Foundry IQ, Fabric IQ, Work IQ |
| [aiappsgbb/foundry-autopilots](https://github.com/aiappsgbb/foundry-autopilots) | Microsoft GBB (community) | **Field lessons** from building compliance- and procurement-officer autopilots: licensing pitfalls, `NO_REPLY`, auth schemes, memory, governance policy, release by pinning |
| [stefanpems/a365-lab-toolkit](https://github.com/stefanpems/a365-lab-toolkit) | Community | Lab across three auth models (OBO, S2S, digital worker) and three hosting models |

### Building blocks

| Repository | Use |
|---|---|
| [microsoft/Agents](https://github.com/microsoft/Agents) (Microsoft 365 Agents SDK) | Activity protocol, `AgentApplication`; defines Agent Blueprint / Agent Identity / Agentic User terms |
| [microsoft/agent-framework](https://github.com/microsoft/agent-framework) | Microsoft Agent Framework (Python/.NET) for richer hosted-agent brains |
| [Azure-Samples/foundry-hosted-agentframework-demos](https://github.com/Azure-Samples/foundry-hosted-agentframework-demos) | Agent Framework agents as Foundry hosted agents |
| [Azure-Samples/m365-multi-agent-workflow](https://github.com/Azure-Samples/m365-multi-agent-workflow) | Multi-agent workflow in a Teams app deployed as a hosted agent |
| [microsoft-foundry/Foundry-Agent-Lab](https://github.com/microsoft-foundry/Foundry-Agent-Lab) | Progressive labs ending with a hosted agent |
| [microsoft-foundry/agent-optimization-workshop](https://github.com/microsoft-foundry/agent-optimization-workshop) | Observe, evaluate, optimize, monitor loop for hosted agents |

### Financial services samples

| Repository | Use for this demo |
|---|---|
| [Azure-Samples/agent-openai-python-banking-assistant](https://github.com/Azure-Samples/agent-openai-python-banking-assistant) | Official multi-agent banking assistant: MCP-wrapped banking APIs, human-in-the-loop approvals |
| [devopsabcs-engineering/foundry-hosted-agents-fsi](https://github.com/devopsabcs-engineering/foundry-hosted-agents-fsi) | Hosted agent with a deterministic calculator, approval gate and an evaluation harness (insurance) |
| [judeper/FSI-AgentGov](https://github.com/judeper/FSI-AgentGov) | FINRA/SEC-aware governance framework for Microsoft 365 agents (Copilot Studio) |
