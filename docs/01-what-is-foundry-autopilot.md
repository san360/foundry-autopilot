# 01 · What is a Foundry autopilot?

> **One-line answer:** an autopilot is a Microsoft Foundry **hosted agent** that is published as a **blueprint**; every team that "hires" it gets its own instance with a Microsoft Entra **agent identity _and_ an agent user account** (mailbox, calendar, OneDrive, Teams presence, place in the org chart, accountable manager), so it can work in Microsoft 365 **as itself**, including in group chats and when no user is present.

Status on 2026-10-26: **public preview** (announced 3 June 2026; still preview in the September 2026 Foundry digest). Creating instances requires the tenant to be enrolled in the **Frontier** program. Sources are listed at the end of this page.

---

## 1. The definition: identity, not features

Microsoft defines the category by **who is acting**, not by what the agent can do:

| Every Foundry agent has… | An autopilot **also** has… |
|---|---|
| A Microsoft Entra **agent identity** (a service principal) created with the agent | An Entra **agent user account** (a user object) per hired instance, with display name, UPN, **manager**, mailbox, calendar, OneDrive, Teams presence and a place in the org chart |

"Capabilities describe an autopilot. Identity establishes it." Memory, proactivity, planning or autonomy do **not** make an agent an autopilot; the distinction is binary: the agent either has its own agent user account or it doesn't.

### Why the agent user account matters

Without it, an agent can only take Microsoft 365 actions **on behalf of a signed-in user**. That breaks in two common situations:

1. **No user in the loop.** An event-triggered agent (an email arrives, a schedule fires) has nobody to act for, so it cannot send mail or edit documents at all.
2. **Group settings.** In a group chat the agent must guess whose permissions to use. Actions get attributed to someone who didn't ask, and members can be exposed to content they can't access.

An autopilot acts as **itself**, with its **own** least-privilege access, so it can serve a whole team, respond to triggers with nobody present, and every action is attributed to it.

## 2. Two different axes: how an agent is *built* vs. how it *acts*

People mix up two questions. "Prompt vs. hosted" is about **how you build and run** the agent. "Assistive vs. background vs. autopilot" is about **which identity it acts with**.

### 2a. How you build it (runtime type)

| Build type | What it is | Who runs the code | Can it be an autopilot? |
|---|---|---|---|
| **Prompt agent** | Declarative: model + instructions + tools, configured in Foundry (portal, SDK or MCP) | Foundry Agent Service | **No** – registry sync and activity data only |
| **Workflow agent** | Declarative orchestration of agents and steps | Foundry Agent Service | No |
| **Hosted agent** | **Your code in a container** (any framework: Agent Framework, LangGraph, M365 Agents SDK, custom) running on Foundry's managed hosted-agent runtime, with Foundry identity, scaling and observability | Foundry hosted runtime (per-session sandboxes) | **Yes – the only type that can be published as an autopilot blueprint** |
| **Managed harness agent** (preview) | A prompt agent that runs on the Foundry-managed GitHub Copilot harness | Foundry | No (it is a prompt agent) |

### 2b. Which identity it acts with (operating type)

| Operating type | Identity | Microsoft 365 actions | Typical use |
|---|---|---|---|
| **Assistive** | Agent identity + **signed-in user context** (on-behalf-of) | Yes, but only with that user's permissions | Personal productivity: a meeting-prep agent that drafts a deck on request |
| **Background service** | Agent identity, app-only permissions | **No** (no user and no agent user account) | Back-end automation: restart a VM when an alert fires |
| **Autopilot** | Agent identity **+ agent user account** | **Yes, as itself**, including in group chats and with nobody present, within the scope you define | Digital coworkers: a release manager or an AML triage analyst working in a team chat |

### 2c. How they combine

| | Assistive | Background service | Autopilot |
|---|---|---|---|
| Prompt agent (published to Teams/Copilot store) | ✅ | ✅ | ❌ |
| Hosted agent | ✅ | ✅ | ✅ (publish with `publishAsAutopilot: true`) |

Agent 365 integration by build type (from the Foundry docs):

| Build type | Agent 365 registry sync | Autopilot publishing | Activity data to Agent 365 |
|---|---|---|---|
| Prompt agent | ✅ | ❌ | ✅ |
| Hosted agent | ✅ | ✅ | ✅ with the Agent 365 SDK |

## 3. You build a blueprint, not an autopilot

A **blueprint** defines (1) what the agent knows how to do (instructions, tools, APIs it can call) and (2) the platform infrastructure it needs (storage, memory). It **never grants access to any team's business data**.

Teams **hire instances** from the approved blueprint. Each instance gets its own agent identity, agent user account, manager, permissions and assignment. This one-to-many shape avoids "ten near-identical agents governed ten different ways":

* **Configure policy once**: every instance inherits it.
* **Update the blueprint**: every instance updates.
* **Block the blueprint**: every instance stops (every instance token chains back to the blueprint credential).
* **Holding a tool is not holding access**: giving an autopilot a SharePoint tool gives it no SharePoint site; a mailbox does not give it the right to send mail anywhere. Access is granted per instance at onboarding.

### Three deployment patterns

| Pattern | Who it serves | Example |
|---|---|---|
| **Group autopilot** | One team; lives where the team works and holds shared context | An AML alert triage analyst hired by the FinCrime Ops – Retail team |
| **Company-wide autopilot** | Everyone; one production instance per business process | An HR policy desk |
| **Personal autopilot** | One person; isolated instance | A developer's own test instance |

## 4. Lifecycle at a glance

| Stage | Layer | Owner | Produces | Reversible |
|---|---|---|---|---|
| Provision infrastructure | Blueprint | Azure administrator | Foundry account/project, model, registry, monitoring, role assignments | Yes |
| Build and publish | Blueprint | Developer | A published blueprint with declared scopes and two ceilings (who can hire, widest access) | Yes |
| Approve, configure, consent | Blueprint | Tenant administrator (Global or AI Administrator) | An activated blueprint; consent to scopes; hiring scope; policy template | Yes |
| Hire | Instance | Manager | Agent identity + agent user account | Yes, by offboarding |
| Onboard | Instance | Manager or access manager | Audience, listening scope, messaging scope, access, source of truth | Yes |
| Operate | Instance | Manager, teammates, business leads | Work, observation, coaching; anyone close to the work can **block** | Yes |
| Offboard | Instance | Manager | Agent user removed, memberships revoked | **No** |
| Retire / delete | Blueprint | Tenant admin / developer | No new hires / blueprint and all instances removed | Retire yes, delete **no** |

Accountability: governance decides who *can* stop an instance (almost anyone close to the work); accountability decides who *must*: always the **manager**. Only a tenant administrator can unblock.

## 5. How it relates to Agent 365, Entra Agent ID and the Copilot "Autopilot"

| Name | What it is | Relationship |
|---|---|---|
| **Microsoft Entra Agent ID** | Identity platform for agents: agent identity blueprints, agent identities, agent users | Provides the identities an autopilot runs on |
| **Microsoft Agent 365** | Enterprise **control plane** for all agents (registry, access control, visualization, interoperability, security with Defender and Purview). GA on 1 May 2026 | Every Foundry agent is registered automatically; autopilot blueprints are approved in the Microsoft 365 admin center and governed as part of the Agent 365 fleet |
| **Foundry autopilot** | **Pro-code** pattern: a hosted agent published as a blueprint and hired by teams | The subject of this repository |
| **Autopilot in the new Microsoft Copilot** (25 Sep 2026, formerly "Scout") | **End-user** experience in the Copilot app: "give it a name, a role and a goal"; lives in your tenant with its own identity, memory, computer and workspace. Private preview from end of September 2026 | Same idea (a digital teammate with its own identity) from a no-code, end-user entry point. Microsoft has not stated that it is implemented as a Foundry autopilot blueprint. Treat that link as an inference |

## 6. When should you use an autopilot?

Use an autopilot when at least one of these is true:

* Work starts **without a user present** (an email, an alert, a schedule) and needs Microsoft 365 actions.
* The agent works **with a group** (team chats, channels, shared mailboxes) and must not borrow one member's permissions.
* The role is **standing and continuous** (owns a queue, follows up, keeps context across surfaces and people).
* Someone must be **accountable** for it: an autopilot has a manager, an audit trail and an off switch.

If none apply, an **assistive** agent is simpler and avoids the preview licensing and approval overhead.

## 7. Glossary

| Term | Meaning |
|---|---|
| Agent identity blueprint | Entra application + service principal created by Foundry when the agent is created; holds the credential every instance token chains back to |
| Agent identity | Service principal the agent authenticates with; for an autopilot it secures the infrastructure that runs the instance |
| Agent user account ("agentic user") | Entra user object per hired instance: display name, UPN, manager, mailbox, Teams presence |
| Hire / instance | Creating an autopilot from a blueprint (Teams **Apps > Agents for your team > Create instance**); consumes one Frontier seat in preview |
| Hiring scope | Who may create instances: None, All users, or specific users/groups (set at approval) |
| Digital worker | API term for an autopilot-capable hosted agent (`digital_worker_type: m365`) |
| Activity protocol | The Microsoft 365 Agents SDK messaging protocol the hosted container serves at `/activity/messages` |

## Sources

* [What is an autopilot in Microsoft Foundry?](https://learn.microsoft.com/azure/foundry/agents/concepts/autopilot-overview) (Microsoft Learn)
* [Autopilot lifecycle in Microsoft Foundry](https://learn.microsoft.com/azure/foundry/agents/concepts/autopilot-lifecycle)
* [Quickstart: Build your first autopilot](https://learn.microsoft.com/azure/foundry/agents/how-to/agent-365)
* [Microsoft Agent 365 integration with Foundry](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-365-integration)
* [From building agents to working with them: enterprise agent distribution in Microsoft Foundry](https://devblogs.microsoft.com/foundry/from-building-agents-to-working-with-them-enterprise-agent-distribution-in-microsoft-foundry/) (3 Jun 2026)
* [What's new in Microsoft Foundry, June 2026](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-june-2026/) and [September 2026](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-september-2026/)
* [Introducing the new Copilot with Home, Code and Autopilot](https://blogs.microsoft.com/blog/2026/09/25/introducing-the-new-copilot-with-home-code-and-autopilot/) (25 Sep 2026)
