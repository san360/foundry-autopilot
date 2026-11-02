# 02 · Prerequisites, licensing and roles

Everything you need **before** a Foundry autopilot can be hired, in the order you hit it. Verified against Microsoft Learn and the Microsoft licensing FAQ on 2026-10-26; preview terms change often, so re-check the linked pages before a customer engagement.

## 1. Checklist

| # | Prerequisite | Why | Who provides it | How to verify |
|---|---|---|---|---|
| 1 | **Microsoft 365 tenant** with Exchange Online and Teams, and an **Azure subscription in the same Entra tenant** | The agent user account gets a mailbox and Teams presence in this tenant; Foundry resources must live in a subscription of the same tenant | Tenant / subscription owner | `az account show --subscription <id>` shows the tenant ID |
| 2 | At least **one Microsoft 365 Copilot or Microsoft Agent 365 licence** (Microsoft 365 E7 includes Agent 365) | Qualifies the tenant for Frontier / Agent 365 previews | Licensing admin | Microsoft 365 admin center > Billing > Licenses, or `scripts/preflight.ps1` |
| 3 | **Frontier program enrollment + Agent 365 terms accepted + 25-seat Frontier subscription** | Gates agents with their own identity ("autopilots"). Your Agent 365 (AGENT_365) licence does **not** replace it | **Global Administrator only** | (a) M365 admin center > **Copilot > Settings > Copilot Frontier** → All users or a group; (b) **Agents > Overview > Try now > I agree**, then complete the **$0 checkout** and pick the **"Microsoft 365 Frontier for Autopilots"** plan. **Billing > Licenses** must then show **25** Frontier licences (also called "Microsoft 365 Frontier for AI Teammates" or "Microsoft Agent 365 Frontier"; Microsoft Graph can list them as `MICROSOFT_AGENT_365_TIER_3`) |
| 4 | **One free Frontier seat per hired instance** | Each instance creates an agent user account, which consumes a seat during preview. **Assigned automatically to the instance's agent user at hire. Never assign it to people** | Tenant admin | Approval wizard shows available autopilot licences; hiring fails with a licence error when none are free |
| 5 | **Approver**: Global Administrator or **AI Administrator** (plus a Microsoft 365 licence) | Approves the blueprint, grants admin consent, selects who can hire | Tenant admin | Name the person before you start |
| 6 | **Hirers / users**: licensed Microsoft 365 users (Teams) inside the hiring scope | Only they see **Create instance** in Teams or Copilot | Tenant admin | Hiring scope chosen in the approval wizard |
| 7 | **Azure RBAC** to provision: **Owner**, or **Contributor + Role Based Access Control Administrator** at resource-group scope | Provisioning creates role assignments (Contributor alone fails half-way) | Azure admin | `scripts/preflight.ps1` |
| 8 | **Foundry User** on the project, **AcrPush** (or Container Registry Repository Writer) on the registry | Build, create the hosted agent version, publish | Azure admin | The scripts assign what they can; Owner covers both |
| 9 | **Region that supports hosted agents** | Hosted runtime availability | Azure admin | See list below; this repo uses **Sweden Central** |
| 10 | **Model quota** for a Responses-API model with tool calling (`gpt-6.1-sol` GlobalStandard, 100K TPM in this repo) | The agent loop calls the model several times per turn | Azure admin | `az cognitiveservices usage list -l <region>` |
| 11 | Tools: Azure CLI, Azure Developer CLI (≥ 1.27.1; tested 1.37.1), azd extension `microsoft.foundry`, PowerShell 7, Python 3.11+ (tests/eval). **Docker is optional**: the image is built in the cloud with ACR Tasks | Deployment scripts | Developer | `scripts/preflight.ps1` |

> You **do not** need an Entra directory role to create the agent: Foundry creates the agent identity blueprint and agent identity when the agent is created.

### Hosted-agent regions (as listed by the official sample)

Australia East, Brazil South, Canada Central, Canada East, East US, East US 2, France Central, Germany West Central, Italy North, Japan East, Korea Central, North Central US, Norway East, Poland Central, South Africa North, South Central US, South India, Southeast Asia, Spain Central, **Sweden Central**, Switzerland North, UAE North, UK South, West Central US, West US, West US 3. Always confirm on [Hosted agents – region availability](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#region-availability).

## 2. Licensing explained

### During preview (Frontier) – what you need today

* The tenant must have at least one **Microsoft 365 Copilot** or **Agent 365** licence (E7 counts). The Agent 365 Frontier page states the requirement as "at least one licence of Microsoft E7"; the Foundry quickstart accepts Copilot or Agent 365. Check both pages for your tenant.
* After enrollment, eligible tenants receive a **25-seat Frontier subscription** through a **$0 checkout** (plan "Microsoft 365 Frontier for Autopilots"; also called "Microsoft 365 Frontier for AI Teammates" or "Microsoft Agent 365 Frontier"). **Each autopilot instance consumes one seat.** Frontier licences are assigned per agent instance and are required before an instance can be created. A regular Agent 365 licence, assigned to people, does not replace them.
* EEA customers can be provisioned Agent 365 Frontier **without Teams licences**.
* **No SLA.** Microsoft states Frontier "should not be used for product evaluations"; use Agent 365 trials for formal evaluations, and position this demo as a preview showcase.
* Field lesson (Microsoft GBB team, not documentation): in one tenant each hire was also assigned an **E7** licence, and hiring failed with a generic licence error while Agent 365 seats looked free. Freeing an E7 seat fixed it. If a hire fails, check every licence pool.

### How many licences this demo needs

| Who | Licence | One-person demo | Full cast (Priya, Elena, Jonas, Lukas) |
|---|---|---|---|
| People: presenter/admin, managers, analyst | Microsoft 365 **E7** (includes Agent 365 and Microsoft 365 Copilot) **+ Teams Enterprise** (this tenant's E7 SKU excludes Teams) | 1 + 1 (your Claimer account) | 4 + 4 |
| Autopilot instances (MiraRetail, TheoCorporate) | 1 **Frontier seat** each, assigned automatically at hire | 2 | 2 |
| Possible extras per instance | A Teams licence through the policy template if the Frontier licence doesn't bundle Teams; in some tenants also an E7 (field lesson above) | up to +2 Teams, +2 E7 | up to +2 Teams, +2 E7 |
| **Total** | | **1 E7, 1 Teams, 2 Frontier** (worst case 3 / 3 / 2) | **4 E7, 4 Teams, 2 Frontier** (worst case 6 / 6 / 2) |

**Zava demo tenant (current deployment):** nothing needs to be bought, but licences must be freed. The 25 Frontier seats already exist (`MICROSOFT_AGENT_365_TIER_3`, a trial until 2026-11-28, 24 free). Each seat also gives the agent user Teams, Exchange Online (Plan 1), OneDrive/SharePoint and the Office apps, so the instances need no separate Teams licence. All 50 E7 licences are assigned to the tenant's demo users and 49 of the 50 Teams Enterprise licences are in use. Your account `sanjaytest` holds only Teams, so a one-person demo needs **1 E7 freed**; the full cast needs 4 E7 and 2 more Teams freed.

**MCAPS tenant MngEnvMCAP809970:** nothing needs to be bought. MCAPS provisioned 50 E7 and 50 Teams licences, of which `admin@` uses one of each, and the 25 Frontier seats cost USD 0 once the tenant is enrolled. `admin@` is already licensed, so a one-person demo could use it without any new licence, but MCAPS asks you to work with the Claimer account.

Assign human licences with `demo/setup-demo-users.ps1` (`-SkipPersonas` for a one-person demo); it never assigns Frontier seats to people.

### At general availability – the per-user model

From the Microsoft licensing FAQ:

| Item | Price / rule |
|---|---|
| **Agent 365 standalone** | **USD 15 per user per month** (list) |
| **Microsoft 365 E7** (includes Agent 365, Microsoft 365 Copilot, Entra Suite and more) | **USD 99 per user per month** (list) |
| Agents, blueprints, instances | **Not licensed separately**; no per-agent or per-instance charges |
| Who must be licensed | Users who **delegate** access to agents (OBO), and the **owner, sponsor or manager** of agents with their own access (autopilots). Microsoft recommends licensing everyone who interacts with, manages or sponsors agents |
| Free for every Microsoft Cloud customer | Agent identity, agent registry, basic usage insights, admin governance actions (publish, deploy, block, delete, approve, reassign), audit logs and eDiscovery for agent activity |
| Premium (licensed users) | Advanced insights, Agent Map, identity governance and lifecycle automation, tool controls, policy templates, Purview DLP / DSPM / Insider Risk / Communication Compliance for agents, Conditional Access and ID Protection for agents, Defender threat detection and hunting |
| Base-licence prerequisites (enterprise) | Microsoft 365 E5, or Microsoft 365 E3 (or O365 E3 + EMS E3) **plus Defender Suite and Purview Suite** |
| Windows 365 for Agents (not needed here) | Separate, USD 0.40 per VM-hour |

**Practical reading for a bank:** a pilot in which a 10-person FinCrime team with 2 managers hires 2 autopilots needs Agent 365 for at least the 2 managers (required: they manage agents with their own access) and, as Microsoft recommends, for all 10 people who work with them. That's USD 30–150 per month standalone on top of their E5 (or E3 + Defender Suite + Purview Suite), or nothing extra if they already hold E7. The two instances themselves are not licensed. Azure consumption comes on top; see [05 · Cost model](05-cost-model.md).

## 3. Roles end to end

### Azure (resource) roles

| Role | Scope | Needed for |
|---|---|---|
| Owner, or Contributor + Role Based Access Control Administrator | Resource group | `azd provision` (creates resources **and** role assignments) |
| Foundry User (formerly Azure AI User) | Foundry project | Create agent versions, publish, run the evaluation harness. **Assigned to the deploying identity by Bicep** (`principalId` = `AZURE_PRINCIPAL_ID`), because Owner has no data-plane rights |
| AcrPush / Container Registry Repository Writer | Container registry | Push the agent image |
| AcrPull (to the project managed identity) | Container registry | Hosted runtime pulls the image (assigned by Bicep) |
| Foundry User (to the agent's default instance identity) | Foundry project | The running agent calls the model (assigned by the creation script) |
| Monitoring Metrics Publisher, Log Analytics Reader (to the project identity) | Application Insights | Traces (assigned by Bicep) |
| Log Analytics Reader for people | Application Insights and its Log Analytics workspace | View traces in the Foundry portal during the demo. **Assigned to the deploying identity by Bicep**; grant other viewers the same. Owner includes it only while active (PIM-eligible Owner must be activated) |
| Foundry Owner (formerly Azure AI Owner), optional | Foundry resource | Start or stop the agent's Azure infrastructure from the Microsoft 365 admin center |
| Search Service Contributor + Search Index Data Contributor (RFP Bid Desk) | Azure AI Search service | Create and load the answer-library indexes. **Assigned to the deploying identity by Bicep** |
| Search Index Data Reader (RFP Bid Desk) | **One index** (`…/searchServices/<svc>/indexes/<index>`) | Each hired bid desk instance's own agent identity (or agent user) reads only its team's library. Assigned by `scripts/grant-bid-team-access.ps1` (Owner or User Access Administrator on the service). The container's default identity gets **no** Search role. See [12](12-rfp-bid-desk.md) |

The Foundry roles were renamed: **Foundry User / Owner / Account Owner / Project Manager** were previously **Azure AI User / Owner / Account Owner / Project Manager**. Role IDs are unchanged.

### Microsoft 365 / Entra roles

| Role | Needed for |
|---|---|
| **Global Administrator** | Enrol in Frontier and accept Agent 365 terms (only GA can do this) |
| **Global Administrator or AI Administrator** | Approve the blueprint, apply a policy template, grant admin consent, set the hiring scope, block or unblock the blueprint. Reader roles can see but not approve |
| Global Reader or AI Reader | View the agent registry and agent details read-only (MCAPS Claimer and Admin accounts hold Global Reader permanently) |
| Purview Audit Reader (role group) | Search agent activity in the audit log |
| Licence / User Administrator | Assign human licences, manage security groups for hiring scope and access |
| Agent ID Administrator (optional) | Manage blueprints, agent identities and agent users in Entra outside the Foundry flow. For the RFP Bid Desk's `agent_user` Search flow: add the delegated Azure AI Search grant to each instance (Cloud Application Administrator also works) |
| **Manager** (any licensed user in the hiring scope) | Hire, onboard, coach, block and offboard an instance |
| Access manager (optional) | Grants an instance access to team resources when the manager can't, then hands over the manager role |

Remove elevated roles granted only for the approval once you are done, and keep a record of them. For the role each demo persona needs, beat by beat, see [07 · FSI demo storyline → Access needed to run the demo](07-fsi-demo-storyline.md#access-needed-to-run-the-demo).

## 4. Network

The default deployment uses public endpoints. The upstream sample also ships a **private networking** variant (`PUBLIC_NETWORK_ACCESS=Disabled`: hub-and-spoke VNet, Azure Firewall, private endpoints) for regulated customers; see `infra/modules/private-networking.bicep`, the upstream sample's private networking README, and [Configure private link for Foundry](https://learn.microsoft.com/azure/foundry/how-to/configure-private-link).

## 5. Readiness of the demo tenants

### Zava demo tenant (current deployment, checked 2026-10-31)

| Check | Result |
|---|---|
| Tenant | `diax07991363.onmicrosoft.com` ("Zava", US), tenant `5b26daf8-1d7a-47f5-bb8d-cbee1e80a381`. Shared: other teams run Foundry autopilot demos here |
| Azure subscription | `ME-DIAx07991363-skomma-1` (`6d0e76b1-b0ba-4757-8582-21d5e95008a7`) in the same tenant ✅, shared with three other Foundry deployments |
| Deploying identity | `sanjaytest@diax07991363.onmicrosoft.com`: **Owner** on the subscription (granted 2026-10-31) and **active Global Administrator** (no PIM) ✅. Bicep grants it **Foundry User** on the project. Licences: Teams Enterprise, plus a freed E7 since 2026-10-31 |
| Qualifying licence | **Microsoft 365 E7 (no Teams)** ×50 ✅, all 50 assigned |
| Human licences | Teams Enterprise ×50 (49 assigned). One E7 was freed for your account (docs/08 Step 3) |
| **Frontier seats** | ✅ 25 (`MICROSOFT_AGENT_365_TIER_3` trial, 2026-10-28 to 2026-11-28): 1 used by another team's autopilot, 2 by MiraRetail and TheoCorporate. Each seat bundles Teams, Exchange, OneDrive/SharePoint and the Office apps |
| Approval | The admin center has no approve or publish button for autopilot blueprints; admin consent works. Instances are created with the Entra APIs (docs/08 Step 5, Option C) |
| Licence lifecycle | Most SKUs show a lifecycle date of 2026-11-15: plan demos before then |
| Region and quota | Sweden Central (hosted agents ✅); `gpt-6.1-sol` GlobalStandard 250K TPM ✅ (100K used by this demo) |
| Resource providers and policies | Providers registered; only Defender for Cloud policy assignments, none affecting Foundry, ACR or monitoring |

### MCAPS tenant MngEnvMCAP809970 (checked 2026-10-27)

The earlier deployment `fsifincrime02` runs in the E7 tenant **MngEnvMCAP809970**. The first tenant (MngEnvMCAP283191: E5 + an Agent 365 trial, no E7) didn't meet the Agent 365 Frontier requirement, so its deployment was torn down.

| Check | Result |
|---|---|
| Tenant | `mngenvmcap809970.onmicrosoft.com` ("Contoso"), tenant `e97a9f8d-6ebb-47d2-8d91-d7727675780f` |
| Azure subscription | `ME-MngEnvMCAP809970-sanjaysingh-1` (`8c3eff54-5f0c-4669-9804-f1eb583379de`) in the same tenant ✅ |
| Deploying identity | `sanjaysingh@MngEnvMCAP809970.onmicrosoft.com` (MCAPS "Claimer"): **Owner** at the tenant root management group ✅. Bicep grants it **Foundry User** on the project. In Microsoft 365 it's a permanent **Global Reader** with **no licence** yet |
| Tenant administrator | MCAPS managed tenant: the Claimer and `admin@mngenvmcap809970.onmicrosoft.com` are permanent Global Readers. **Global Administrator is PIM-eligible**: activate it (MFA, up to 4 hours) before Frontier enrollment, licence assignment and approval. The only standing Global Administrators are MCAPS automation service principals and a break-glass account that must not be used |
| Qualifying licence | **Microsoft 365 E7 (no Teams)** ×50 (1 assigned). It includes the AGENT_365 and Microsoft 365 Copilot service plans ✅ |
| Human licences | Teams Enterprise ×50 (1 assigned); 49 free E7 + Teams for your account and the demo personas |
| **Frontier seats** | ⚠️ **Not present** (checked 27 Oct, 17:37). Until they are, the request in the admin center shows *"Blueprint agents are only supported in Frontier tenants"*. **Action:** activate Global Administrator in PIM, then M365 admin center > Agents > Overview > **Try now** > **I agree** > complete the **$0 checkout** with the "Microsoft 365 Frontier for Autopilots" plan, then confirm 25 Frontier licences under Billing > Licenses |
| Region and quota | Sweden Central (hosted agents ✅); `gpt-6.1-sol` GlobalStandard 250K TPM ✅ (100K used by this demo) |
| Resource providers and policies | Fresh subscription: the six providers are registered by the preprovision hook; no Azure Policy assignments |

Run `pwsh ./scripts/preflight.ps1 -SubscriptionId <id> -Location swedencentral` at any time to re-check.

## Sources

* [Quickstart: Build your first autopilot – prerequisites](https://learn.microsoft.com/azure/foundry/agents/how-to/agent-365#prerequisites)
* [Preview Microsoft Agent 365 features through the Frontier program](https://learn.microsoft.com/microsoft-agent-365/frontier)
* [Microsoft Agent 365 licensing FAQ](https://www.microsoft.com/licensing/faqs/122)
* [Agent 365 overview and prerequisites](https://learn.microsoft.com/microsoft-agent-365/overview)
* [Hosted agent permissions reference](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions)
* [aiappsgbb/foundry-autopilots](https://github.com/aiappsgbb/foundry-autopilots) (field lessons, community)
