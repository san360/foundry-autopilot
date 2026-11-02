# 08 · Deployment runbook

Status on 2026-11-01: **two autopilots deployed in the Zava demo tenant and verified end to end.** *FinCrime Alert Triage*: MiraRetail and TheoCorporate, first created with the Entra Agent ID APIs (Step 5, Option C) and **rehired in the Microsoft 365 admin center** on 2026-11-01 so they appear in Agent 365; MiraRetail answers in Teams and replies to alert emails. *RFP Bid Desk* (Step 8, [doc 12](12-rfp-bid-desk.md)): BankingBids and PublicSectorBids, created with the Entra APIs after a Graph admin consent; each reads only its own Azure AI Search index (`/whoami probe`: 200 own, 403 other, 403 container). How the pieces fit and who grants what: [doc 13](13-identity-analogy-and-hiring.md). An earlier deployment, `fsifincrime02` in the E7 MCAPS tenant, is still in place but can't be approved until that tenant is enrolled in Frontier (Step 2). The first deployment (`fsifincrime01`, tenant MngEnvMCAP283191) was torn down on 2026-10-27; see [Teardown](#teardown-in-this-order).

| Item | Zava demo tenant (current) | MCAPS E7 tenant (earlier) |
|---|---|---|
| Tenant | `diax07991363.onmicrosoft.com` ("Zava", tenant ID `5b26daf8-1d7a-47f5-bb8d-cbee1e80a381`), shared with other teams' autopilot demos | `mngenvmcap809970.onmicrosoft.com` ("Contoso", tenant ID `e97a9f8d-6ebb-47d2-8d91-d7727675780f`) |
| Licences | 50× Microsoft 365 E7 (no Teams) and 50× Teams Enterprise, **all but one Teams assigned**; 25× Frontier seats (`MICROSOFT_AGENT_365_TIER_3` trial until 2026-11-28, 1 used by another team). Most SKUs show a lifecycle date of 2026-11-15 | 50× Microsoft 365 E7 (no Teams), 50× Teams Enterprise (1 of each in use); no Frontier seats yet |
| Subscription / resource group / region | `ME-DIAx07991363-skomma-1` (`6d0e76b1-b0ba-4757-8582-21d5e95008a7`, shared) / `rg-fsi-autopilot` / Sweden Central | `ME-MngEnvMCAP809970-sanjaysingh-1` (`8c3eff54-5f0c-4669-9804-f1eb583379de`) / `rg-fsi-autopilot` / Sweden Central |
| Deploying identity | `sanjaytest@diax07991363.onmicrosoft.com`: **Owner** on the subscription (PIM-eligible: activate before `azd`), **active Global Administrator** (no PIM) | `sanjaysingh@MngEnvMCAP809970.onmicrosoft.com` (MCAPS "Claimer"): **Owner** at the tenant root management group; permanent **Global Reader**, Global Administrator PIM-eligible (Step 2a) |
| azd environment | `fsifincrime03` (default) | `fsifincrime02` |
| Foundry project endpoint | `https://fsifincrime03acct.services.ai.azure.com/api/projects/fsifincrime03proj` | `https://fsifincrime02acct.services.ai.azure.com/api/projects/fsifincrime02proj` |
| Hosted agent | `fsifincrime03-fincrime-autopilot` (version 5 serves all traffic, `digital_worker_type: m365`) | `fsifincrime02-fincrime-autopilot` (version 1 active) |
| Entra agent identity blueprint | `fsifincrime03acct-fsifincrime03proj-fsifincrime03-fincrime-autopilot-f6077-AgentIdentityBlueprint` (client ID `069c4c09-3c03-44fb-b365-f02c72c9afde`) | `…-fsifincrime02-fincrime-autopilot-be106-AgentIdentityBlueprint` (client ID `fa6ab88b-a283-46f3-826c-255893c21d28`) |
| Microsoft 365 publication | "FinCrime Alert Triage" v1.0.0, Teams app ID `938ebfab-e374-4e7d-bd91-3433ea6050ec`; admin consent granted, no approval button in the admin center (Step 4) | Teams app ID `6787bc41-b6c1-486e-8299-cded810caa33`, pending review |
| RFP Bid Desk (Step 8) | Hosted agent `fsifincrime03-rfp-bid-desk` (version 3), Azure AI Search `fsifincrime03-bids-search` in **North Europe** (no Search capacity in Sweden Central), Teams app `1a7b9a56-0fdd-430f-a292-91ee06ef25f4`, blueprint client ID `887b8e0d-e235-4919-a668-df5608b32db7`. Hires created with the Entra APIs on 2026-11-01: **BankingBids** (agent user `76c77979-bc7e-4c05-b466-2c839cc4f1b0`, agent identity `35b5cd0a-…`) and **PublicSectorBids** (agent user `29af247c-8897-4be3-a50f-6164e4c82afb`, agent identity `94b2c6ce-…`), each with Search Index Data Reader on its own index only. Verified end to end ([doc 12 §11](12-rfp-bid-desk.md)) | none |
| Hired instances | **MiraRetail** (`miraretail@…`, agent user `2ec47a73-3225-4ec6-9269-115f9f20c1ff`) and **TheoCorporate** (`theocorporate@…`, agent user `1dbce47c-e7a8-4ea3-8486-e561d41015d4`), manager `sanjaytest`, one Frontier seat each, rehired in the Microsoft 365 admin center on 2026-11-01 (the earlier Entra-API instances were deleted because they did not appear in Agent 365) | none |

The commands below use the Zava values; substitute the other column for the MCAPS tenant. Switch between environments with `azd env select <name>`, and point the az CLI default subscription at the same tenant.

## Step 0 – Sign in with the right identity (developer)

```powershell
az login --tenant 5b26daf8-1d7a-47f5-bb8d-cbee1e80a381 --use-device-code   # sign in as sanjaytest@diax07991363.onmicrosoft.com
az account set --subscription 6d0e76b1-b0ba-4757-8582-21d5e95008a7         # azd uses the az CLI identity (auth.useAzCliAuth=true)
pwsh ./scripts/preflight.ps1 -SubscriptionId 6d0e76b1-b0ba-4757-8582-21d5e95008a7 -Location swedencentral
```

The scripts bind every token to the subscription, but the az CLI **default subscription** must point to this subscription when you run `azd`: `--tenant` tokens come from the default account's user, which may be a different (guest) identity. The az CLI lists subscriptions only as they were at sign-in: after you are granted a role on a subscription, sign in again.

## Step 1 – Provision, build and publish (developer, automated) ✅ done

```powershell
azd env new fsifincrime03 --subscription 6d0e76b1-b0ba-4757-8582-21d5e95008a7 --location swedencentral
azd env set AZURE_RESOURCE_GROUP rg-fsi-autopilot
azd env set ALLOWED_SENDER_DOMAINS diax07991363.onmicrosoft.com
az group create --subscription 6d0e76b1-b0ba-4757-8582-21d5e95008a7 -n rg-fsi-autopilot -l swedencentral
azd provision          # providers + Bicep + post-provision hook (Toolbox, ACR build, agent version, publish)
pwsh ./scripts/smoke-test.ps1 -RunEval
```

On a fresh subscription the preprovision hook registers the six resource providers it needs. Bicep grants the deploying identity **Foundry User** on the project (Owner alone has no data-plane access), and the post-provision hook waits for that role to propagate.

Code changes later: `azd hooks run postprovision` builds a new image, creates a **new agent version** (traffic goes to `@latest`) and re-publishes idempotently. Bump `AGENT_APP_VERSION` only when publication metadata changes (that needs re-approval). Sessions stay pinned to the version they started on, even when stopped, and Teams chats and email threads resume their session. So once the new version is active, the hook runs `scripts/stop-agent-sessions.ps1`, which **deletes the sessions pinned to older versions**. It finds them through the sessions API and through Application Insights, because the API misses Teams and email sessions. Run it yourself after any other version change.

## Step 2 – Enroll the tenant in Frontier (Global Administrator) ✅ done in Zava · ⚠️ to do in MngEnvMCAP809970

**Zava demo tenant:** already enrolled. Graph and the preflight show the 25 Frontier seats as `MICROSOFT_AGENT_365_TIER_3`, which bundles Teams, Exchange Online (Plan 1), OneDrive/SharePoint and the Office apps for each agent user. Skip to Step 3.

### 2a – Activate Global Administrator in PIM (MCAPS managed tenants)

In MCAPS Managed Environment tenants, the **Claimer** account (`sanjaysingh@MngEnvMCAP809970.onmicrosoft.com`, preferred) and the **Admin** account (`admin@…`) are permanent **Global Readers**. Privileged roles, including **Global Administrator**, are only **PIM-eligible**. While the role isn't activated, the admin center hides **Try now**, the **Copilot Frontier** setting and the approval actions.

1. Open [Privileged Identity Management → My roles](https://portal.azure.com/#view/Microsoft_Azure_PIMCommon/CommonMenuBlade/~/quickStart) (or the Entra admin center → ID Governance → Privileged Identity Management) signed in with the Claimer account.
2. **Microsoft Entra roles → Eligible assignments → Global Administrator → Activate**: complete MFA, enter a justification, and choose a duration (maximum **4 hours**).
3. Sign out of the Microsoft 365 admin center and sign in again so the new role takes effect.
4. Do Steps 2b, 3 and 4 inside the same activation window: Frontier enrollment, licence assignment and blueprint approval all need it.

If Global Administrator isn't listed under eligible assignments, ask the tenant's owners to add an eligible assignment for your account.

### 2b – Enroll in Agent 365 Frontier

Your **Agent 365 or E7 licence is not enough on its own.** It's a per-person licence: it qualifies the tenant and covers you as a manager, but it is never assigned to an agent. Creating an autopilot instance in preview needs a separate **25-seat Frontier subscription**, one seat per instance. The docs use three names for it: "Microsoft 365 Frontier for AI Teammates", "Microsoft 365 Frontier for Autopilots" and "Microsoft Agent 365 Frontier". It costs **$0** but arrives through a checkout.

1. Sign in to the [Microsoft 365 admin center](https://admin.cloud.microsoft) with **Global Administrator active** (Step 2a). The Claimer account is preferred; `admin@mngenvmcap809970.onmicrosoft.com` works the same way.
2. **Copilot > Settings > View all**, search "Frontier" → **Copilot Frontier** → **All users** (or a specific group). This enrolls users in the Frontier program (AI Administrator, Security Administrator or Office Apps Administrator role).
3. **Agents > Overview** → banner **Try now** → **I agree** to the Agent 365 terms of service. Alternative entry point: **Home > Dashboard view** → Agent 365 card → **Try now**. Only a Global Administrator can do this.
4. **Complete the $0 checkout** that follows: "purchase" the $0 Agent 365 SKU with **25 agent-instance licences** and, when prompted, select the **Microsoft 365 Frontier for Autopilots** plan. Accepting the terms alone does not create the seats.
5. **Billing > Licenses**: confirm **25** Frontier licences. Frontier changes can take a few hours to appear.
6. Re-run `scripts/preflight.ps1`; the Frontier check should turn **OK**. It lists every SKU in the tenant if the seats are still missing.

**Eligibility.** The Agent 365 Frontier page requires **at least one Microsoft E7 licence** in the tenant. Both demo tenants have 50 E7 (no Teams) licences, so they qualify. (The first tenant, MngEnvMCAP283191, had only E5 plus an Agent 365 trial.)

**Don't assign Frontier licences to people.** Each one is consumed automatically by an autopilot instance's own **agent user** when a manager clicks **Create instance** (one per instance). Humans need ordinary licences instead:

| Who | Licences | In the Zava tenant (MCAPS tenant) |
|---|---|---|
| Approver (Global or AI Administrator) | Microsoft 365 (Teams + Exchange) | `sanjaytest`, an active Global Administrator (Claimer or `admin@…` with Global Administrator **activated in PIM**, Step 2a) |
| Manager who hires and owns an instance | Microsoft 365 with Teams + Exchange; **Agent 365** (included in E7, and required at GA: licensing is per responsible human) | Your account once it holds an E7 (Step 3), or Elena and Lukas |
| Teammates who chat with the instance | Microsoft 365 (Teams) | Jonas from Step 3 |
| The autopilot instance (agent user) | 1 Frontier seat, assigned automatically at hire | MiraRetail, TheoCorporate. In Zava the seat also brings Teams, Exchange and OneDrive |

## Step 3 – Licence your account and optionally create demo personas (Global or User Administrator)

**Zava:** `sanjaytest@diax07991363.onmicrosoft.com` holds only **Teams Enterprise**: no mailbox, Copilot or Agent 365, so it can't send the alert emails or act as a full manager. All 50 E7 licences are assigned to the tenant's demo users, so first **unassign one**: Microsoft 365 admin center → **Billing → Licenses → Microsoft 365 E7 (no Teams)** → a demo user nobody else relies on (the tenant is shared) → **Unassign**. Then:

```powershell
$sub = "6d0e76b1-b0ba-4757-8582-21d5e95008a7"
pwsh ./demo/setup-demo-users.ps1 -UseAzCli -SubscriptionId $sub -AlsoLicense sanjaytest@diax07991363.onmicrosoft.com -SkipPersonas          # dry run: needs 1 E7
pwsh ./demo/setup-demo-users.ps1 -UseAzCli -SubscriptionId $sub -AlsoLicense sanjaytest@diax07991363.onmicrosoft.com -SkipPersonas -Apply   # one-person demo
```

The script skips licences you already hold (here Teams) and never assigns Frontier seats or device licences to people. The full cast (Elena, Jonas, Lukas: drop `-SkipPersonas`) needs **4 E7 and 3 Teams** in total, and only 1 Teams is free today, so free 4 E7 and 2 Teams first or run a one-person demo. The dry run prints what's missing and `-Apply` stops before any change if licences are short. Alternatively, play every role with an account that is already licensed, such as `admin@diax07991363.onmicrosoft.com` (MOD Administrator, E7 + Teams), if you have its credentials.

**MCAPS tenant:** your Claimer account has no licence yet. Run the script with **Global Administrator activated in PIM** (Step 2a) and consent to the requested Graph scopes. It picks **E7 (no Teams) + Teams Enterprise** automatically and uses 4 of the 49 free E7 and Teams licences:

```powershell
pwsh ./demo/setup-demo-users.ps1 -AlsoLicense sanjaysingh@MngEnvMCAP809970.onmicrosoft.com          # dry run
pwsh ./demo/setup-demo-users.ps1 -AlsoLicense sanjaysingh@MngEnvMCAP809970.onmicrosoft.com -Apply   # licence you + create Elena, Jonas, Lukas + "FinCrime Team Leads"
```

Initial passwords are printed once to your console. Undo the personas with `-Remove`.

## Step 4 – Approve the blueprint (Global or AI Administrator)

1. [Microsoft 365 admin center → Agents → All agents → Requests](https://admin.cloud.microsoft/?#/agents/all/requested) → **FinCrime Alert Triage** (state *Pending activate*).
2. **Publish to users**: confirm host products and audience; under **Activate**, choose **Specific users or groups** → *FinCrime Team Leads* (or *All users* for a quick demo). This is the **hiring scope**.
3. **Apply template**: keep the Microsoft default policy template (shows available autopilot licences). For a customer or production tenant, pick a template from [14 · Agent policy templates](14-agent-policy-templates.md) instead: the choice can't be changed after approval.
4. **Accept permissions**: review Mail, Teams, Word, Excel, OneDrive/SharePoint and Calendar scopes, plus observability → **Grant admin consent**.
5. **Review and finish** → **Publish**. Verify on the **Registry** tab: status **Available**.

The portal can look as if consent reset; check the Registry tab and the audit log before redoing it.

**Zava, 2026-10-31:** the admin center offered no button to approve or publish the autopilot blueprint (a known UI problem for autopilots), but **Accept permissions** worked: the audit log shows the admin consent on the blueprint. That consent is all that Option C below needs.

## Step 5 – Create (hire) the instances

**Prerequisites:** Frontier seats exist (Step 2), the blueprint shows **Available** on the Registry tab (Step 4), and whoever creates the instance is in the hiring scope (or is a Global or AI Administrator). Option C needs only the blueprint's admin consent.

**Option A: the manager hires in Teams (show this live in the demo).**
1. As Elena (or your own account for a one-person demo), open Teams → **Apps → Agents for your team**, or Microsoft 365 Copilot → **Agents → Agents for your team**.
2. Select **FinCrime Alert Triage** → **Create instance**. If you see **Request instance** instead, you're outside the hiring scope; the request goes to the admin's Requests tab.
3. Enter the name, alias and domain from the table below, confirm the manager, then select **Create**.

**Option B: an admin creates it on behalf of a manager (use this to prepare the day before).**
1. Microsoft 365 admin center → **Agents → All agents → Registry** → **FinCrime Alert Triage** (status *Available*) → **Create instance**.
2. Work through the wizard: **select the manager** → **licence validation** (needs a free Frontier seat) → instance customization (name, alias) → **review and confirm**.

**Option C: create it with the Microsoft Entra Agent ID APIs (when the approval or hire UI isn't available).** ✅ Used in Zava on 2026-10-31.

```powershell
pwsh ./scripts/create-instance-entra.ps1 -Name MiraRetail -Alias miraretail -Manager sanjaytest@diax07991363.onmicrosoft.com            # plan
pwsh ./scripts/create-instance-entra.ps1 -Name MiraRetail -Alias miraretail -Manager sanjaytest@diax07991363.onmicrosoft.com -Apply
pwsh ./scripts/create-instance-entra.ps1 -Name TheoCorporate -Alias theocorporate -Manager sanjaytest@diax07991363.onmicrosoft.com -Apply
```

It uses your Azure CLI sign-in (Global Administrator), Microsoft Graph beta, and reproduces the setup of the other team's working "Agentic Colleague Autopilot" in the same tenant:

1. **Agent identity** from the blueprint (`POST /servicePrincipals/microsoft.graph.agentIdentity`), with the manager as **owner and sponsor**.
2. **Agent user** (`POST /users/microsoft.graph.agentUser`) parented by that identity (`identityParentId`), with the **manager** and a usage location.
3. **Frontier seat** through `assignLicense`: the SKU with the `AGENT_365_TOOLS` plan. In Zava that's `MICROSOFT_AGENT_365_TIER_3`, which already includes Teams, Exchange and OneDrive, so no E5 or E7 goes to the agent. In tenants with `MICROSOFT_AGENT_365_ROW`, the script picks that instead, and it swaps out E5/E7 in the same call.
4. **Delegated grants on the agent identity**, the same scopes as the blueprint's admin consent: Agent Tools `McpServers.*`, Messaging Bot API `AgentData.ReadWrite`, and Agent365Observability `OtelWrite`. Direct creation doesn't add them, and the reference instance needed them.

Graph's `AgentIdUser.ReadWrite.IdentityParentedBy` application role on the blueprint principal isn't needed when an admin creates agent users with a delegated token, and the reference blueprint doesn't have it. Add `-GrantBlueprintAppRole` if the blueprint itself must create agent users. Teams agent settings can show "This agent can't be found" for instances created this way, while chat and email work. They also don't appear under the agent's **Instances** in the Microsoft 365 admin center (Agent 365 registry), so prefer Option A or B once the blueprint is published.

**Teams entitlement (all options):** for agent users, Teams activities carry only the agent user's object ID, not the instance name; email notifications carry both. Map each instance's agent-user ID in `SEGMENT_SCOPE_RULES` (it replaces the built-in rules, so keep the keywords), then roll out a new agent version:

```powershell
azd env set SEGMENT_SCOPE_RULES '{"retail":["Retail","Wealth"],"wealth":["Retail","Wealth"],"corporate":["Corporate & SME"],"corp":["Corporate & SME"],"sme":["Corporate & SME"],"cib":["Corporate & SME"],"2ec47a73-3225-4ec6-9269-115f9f20c1ff":["Retail","Wealth"],"1dbce47c-e7a8-4ea3-8486-e561d41015d4":["Corporate & SME"]}'
azd hooks run postprovision
```

Without the mapping, the logs show `entitled segments=all segments` for Teams turns and the cross-team refusal beat fails in Teams.

| Field | Retail instance | Corporate instance |
|---|---|---|
| Name (≤ 32 characters; Agent 365 advises **no spaces or special characters**) | `MiraRetail` | `TheoCorporate` |
| Alias (mailbox) | `miraretail` | `theocorporate` |
| Manager | Elena Brandt (or your account) | Lukas Meyer (or your account) |

Keep **Retail** / **Corporate** in the name: the demo derives each instance's data entitlement from it. CamelCase names and lower-case aliases are both recognised.

Provisioning takes about **5 minutes** (sometimes longer). The instance then messages its manager in Teams and appears in the org chart; the mailbox can lag behind. Each instance consumes **one Frontier seat**. Verify with `pwsh ./scripts/smoke-test.ps1`, which lists the instances hired from this environment's blueprint with their manager and licences (other teams' autopilots in a shared tenant are only counted).

## Step 6 – Onboard (managers)

1. Create the group chats **"FinCrime Ops – Retail & Wealth"** (Elena, Jonas, MiraRetail) and **"FinCrime Ops – Corporate & SME"** (Lukas, TheoCorporate).
2. Optional: `azd env set TRIAGE_NOTIFY_CHAT_NAME "FinCrime Ops – Retail & Wealth"` then `azd hooks run postprovision`, so email-triggered triages also post a summary in the chat.
3. Test: `@MiraRetail what's in our alert queue?` and `pwsh ./demo/send-tm-alert.ps1 -To miraretail@diax07991363.onmicrosoft.com -AlertId ALR-2026-1043` (the sender needs a mailbox: in Zava, the E7 from Step 3).

## Step 7 – Before every demo

1. MCAPS tenants: activate **AI Administrator** (or Global Administrator) in PIM for the admin persona (MFA, ≤ 4 h), then sign out and back in to admin.cloud.microsoft. In Zava, `sanjaytest` is a standing Global Administrator. The full role matrix is in [docs/07 → Access needed to run the demo](07-fsi-demo-storyline.md#access-needed-to-run-the-demo).
2. Run the checks:

```powershell
pwsh ./scripts/smoke-test.ps1 -RunEval     # configuration + two live scenarios
.\.venv\Scripts\python.exe eval\run_scenarios.py --endpoint https://fsifincrime03acct.services.ai.azure.com/api/projects/fsifincrime03proj --model gpt-6.1-sol --subscription 6d0e76b1-b0ba-4757-8582-21d5e95008a7   # full suite, ~USD 0.15
```

## Step 8 – Optional: RFP Bid Desk (second autopilot, per-instance Azure access)

Full details: [12 · RFP Bid Desk](12-rfp-bid-desk.md#8-deploy). In short:

1. Developer: `azd env set ENABLE_BID_DESK true`, optionally `azd env set BID_TEAM_CHAT_NAME "Woodgrove bid team"`, then `azd provision -e <env> --no-prompt`. This adds Azure AI Search (`<env>-bids-search`, keys disabled), loads the `bids-banking` and `bids-publicsector` indexes, creates the hosted agent `<env>-rfp-bid-desk` (`AUTOPILOT_SCENARIO=rfp`, `TOKEN_DEBUG=true`) and publishes **"RFP Bid Desk"**. Its azd values use the `BID_DESK_` prefix.
2. Global or AI Administrator: approve "RFP Bid Desk" (as in Step 4).
3. Manager: hire **BankingBids** and **PublicSectorBids** (2 Frontier seats). Then map their agent-user and agent-identity IDs in `BID_TEAM_RULES` (Teams activities carry only the IDs) and roll out a new version ([doc 12 §8](12-rfp-bid-desk.md#8-deploy)). API-only alternative to steps 2–3: [doc 12 §8](12-rfp-bid-desk.md#8-deploy).
4. Owner or User Access Administrator: give each instance its own index only:
   `pwsh ./scripts/grant-bid-team-access.ps1 -Instance BankingBids -Team banking -Apply` (and `PublicSectorBids` / `publicsector`).
5. Verify after a few minutes: `/whoami probe` to each instance in Teams. Expect HTTP 200 on its own library, 403 on the other, and 403 for the shared container identity. If the default `agent_identity` flow doesn't return a token, switch `BID_DESK_SEARCH_TOKEN_FLOW` (§4 of doc 12) and re-run the grant script with the matching `-Flow`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `RequestConflict: Another operation is in progress` on the Foundry project during the first `azd provision` | Upstream Bicep creates the project and model deployment in parallel on the same account | **Fixed here**: the model deployment now depends on the project. Re-run `azd provision` |
| `az acr build` crashes with `UnicodeEncodeError: 'charmap' codec…` on Windows, although the build succeeds in ACR | The Azure CLI log streamer writes non-ASCII build output to a cp1252 console | **Fixed here**: the build is queued with `--no-wait` and polled with `az acr task show-run` |
| Scripts get 401/403 from Foundry or Graph while you are Owner | `az … --tenant` picked another identity (for example a guest) in the tenant, or the az default subscription points elsewhere | **Fixed here**: tokens use `--subscription`; keep the az default subscription on the target subscription when running `azd` |
| Post-provision hook waits "for the 'Foundry User' role assignment to propagate" | Fresh subscription: Owner has no Foundry data-plane rights until the Bicep role assignment propagates | Expected for 1–2 minutes; the hook continues automatically (10-minute limit) |
| Post-provision hook fails at *Creating Toolbox* with `get_toolbox: … AzureDeveloperCLICredential: exit status 1` | Transient: azd couldn't get a token through the az CLI while resolving the environment's subscription (seen once in Zava, 2026-10-31) | Re-run `azd hooks run postprovision`; the hook is idempotent |
| `az account set` or the scripts report the subscription as not found, although you were just given a role on it | The az CLI caches the subscription list at sign-in | Sign in again: `az login --tenant <tenant-id>` |
| Smoke test shows "Other autopilots in the tenant" | Shared tenant: other teams' autopilot instances are agent users too | Informational. The smoke test and teardown only act on instances hired from this environment's blueprint (`agentIdentityBlueprintId`) |
| `azd provision` fails with resource provider not registered | Fresh subscription | The preprovision hook registers all six providers; re-run `azd provision` |
| Preflight shows Frontier **ACTION** | Tenant not enrolled | Step 2 |
| No **Try now** banner, no **Copilot Frontier** setting, or approval buttons missing when signed in as `admin@` or the Claimer | MCAPS managed tenant: the account is a permanent Global Reader; Global Administrator is only PIM-eligible | Activate Global Administrator in PIM (Step 2a), then sign out and back in to the admin center |
| Request shows **"Blueprint agents are only supported in Frontier tenants"** (status *Pending review*) | The tenant has no Agent 365 Frontier subscription yet; autopilot blueprints can't be activated without it | Do Step 2 as a Global Administrator (Try now → I agree → $0 checkout). Once **Billing > Licenses** shows the 25 Frontier seats, reopen the request and run the approval wizard (Step 4). No redeploy or republish is needed |
| No "Copilot Frontier" setting, or no Frontier licences after **Try now** | Eligibility: some Frontier pages require a Microsoft 365 Copilot or E7 licence in the tenant | Add one Copilot or E7 licence, then repeat Step 2 |
| **Create instance** missing or disabled | Not approved, you're outside the hiring scope, or no Frontier enrollment | Check Registry status, hiring scope, Frontier |
| The admin center shows the autopilot request but no button to approve or publish it | Admin center UI problem for autopilot blueprints (Zava, 2026-10-31) | Grant the admin consent (**Accept permissions**), then create the instances with `scripts/create-instance-entra.ps1` (Step 5, Option C) |
| An instance shows other teams' alerts in Teams; logs show `entitled segments=all segments` | Teams activities carry only the agent user's object ID, not the instance name | Map the agent-user IDs in `SEGMENT_SCOPE_RULES` and run `azd hooks run postprovision` (Step 5) |
| Teams agent settings show "This agent can't be found" | Instance created with the Entra APIs | Known limitation; chat and email work |
| Email turns showed `result=failure` in the traces, or a Word/Excel comment reply showed `BadArgument … Activity type 'typing' is not supported for agent channel` | The host sent a typing indicator on the `agents` channel (email, document comments), which only accepts message and event activities. Comment @mentions also went to the chat handler instead of the comment flow | **Fixed here**: typing indicators go only to chat channels, and comment @mentions use the comment flow (reply posted with `ReplyToComment`). A warning "Failed to save response_id" on email turns (file name too long for email conversation IDs) is harmless; follow-ups in the same email thread start without the previous turn |
| Foundry portal traces: "You don't have permissions to view data from the connected Application Insights resource … Log Analytics Reader role or higher" | Owner is PIM-eligible but not activated, or the viewer has only Foundry User | Activate Owner in PIM, or re-run `azd provision`: Bicep now grants the deploying identity **Log Analytics Reader** on Application Insights and its workspace. Grant other viewers the same role |
| `azd provision` with `ENABLE_BID_DESK=true` fails with `InsufficientResourcesAvailable: The region '…' is currently out of the resources required` | No Azure AI Search capacity in the main region (Sweden Central, 2026-11-01) | `azd env set BID_DESK_SEARCH_LOCATION northeurope` (or another nearby region with the semantic ranker: Norway East has none and fails with "Semantic Search is not available") and re-run `azd provision`. Only the Search service moves; latency to it is negligible for this demo |
| Hire fails with a licence error although seats look free | No free Frontier seat (or, in some tenants, no free E7 seat) | Offboard an unused instance or free a seat |
| Email to the instance bounces `550 5.1.10` | Mailbox still provisioning after hire | Wait; Teams works first. Hire the day before a demo |
| Teams works but email-triggered alerts get no reply | Sender not in `ALLOWED_SENDER_DOMAINS`, or endpoint auth `BotServiceRbac` | Check the sender domain; this repo already uses `Entra` + `BotServiceTenant` |
| Replies in Teams but cannot read or send mail or create Word docs | Admin consent not granted for the Microsoft 365 scopes | Re-check the consent step; publish with a higher `AGENT_APP_VERSION` if scopes changed |
| Instance says an alert belongs to another team | Entitlement from the instance name | Expected for cross-team alerts; rename or set `SEGMENT_SCOPE_RULES` |
| Old behaviour after a code or configuration change (traces label the turn with the new version, but the logs show the old settings) | The conversation resumed a session pinned to the old version. Stopping doesn't unpin a session, and the sessions list API misses Teams and email sessions (Zava, 2026-10-31) | `pwsh ./scripts/stop-agent-sessions.ps1` deletes sessions pinned to older versions, found through the API and Application Insights; the post-provision hook runs it after creating the version |
| "Blocked by … content-safety controls" reply | Azure AI Content Safety Prompt Shields flagged a jailbreak or injection | Expected for attack prompts; the agent returns a policy message |
| Group chat noise | `canRespondWithoutMention` true | This repo publishes with `false`; @mention the instance |
| RFP Bid Desk: `/whoami probe` shows "Search token … unavailable" for `agent_identity` | The blueprint exchange token or the instance's client-credentials request failed (the error text shows the Entra code) | Try `session_identity` or `agent_user` (`azd env set BID_DESK_SEARCH_TOKEN_FLOW …`, `azd hooks run postprovision`) and re-run `grant-bid-team-access.ps1` with the matching `-Flow` |
| RFP Bid Desk: an instance gets HTTP 403 on **its own** library | Role assignment missing, on the other principal type (agent identity vs agent user), or not yet propagated | Re-run `grant-bid-team-access.ps1` (plan mode shows what exists); wait a few minutes |
| RFP Bid Desk: an instance can read **another** team's library | A Search data role at service, resource group or subscription scope | The grant script warns about these; remove them. Only index-scope Search Index Data Reader is expected |
| RFP Bid Desk: an MCP tool is missing ("MCP tools offered by …" log line) | The server's tool names differ from `allowedTools` in `ToolingManifest.rfp.json` | Fix the list, or set `MCP_ENFORCE_ALLOWLIST=false` temporarily |

Hosted agent logs for a session ID shown in an error: see the upstream sample README, or open the agent in the Foundry portal or in **Foundry Canvas → Deploy & test → Inspect locally**.

## Teardown (in this order)

```powershell
pwsh ./scripts/teardown.ps1 -Environment <azd-env-name> -DeleteEntraObjects
```

The script:
1. Stops if instances hired from this environment's blueprints (agent users) exist, including RFP Bid Desk hires; other teams' instances in a shared tenant are ignored. Delete yours first in the **Microsoft 365 admin center → Agents**: offboard or delete the instances (MiraRetail, TheoCorporate, BankingBids, PublicSectorBids). This frees the Frontier seats and removes the agent users and mailboxes.
2. Deletes the hosted agents (FinCrime and, if deployed, the RFP Bid Desk) through the Foundry data plane.
3. Runs `azd down --force --purge`: resource group, purged Foundry account and Log Analytics workspace.
4. Verifies the resource group is gone and deletes leftover Entra agent identity objects named after this environment.
5. Reminds you of the last manual step: **Microsoft 365 admin center → Agents → All agents → FinCrime Alert Triage → Permanently delete** (or reject it on the Requests tab if it was never approved).

Optional: remove the demo personas with `pwsh ./demo/setup-demo-users.ps1 -Remove`.

Deleting Azure resources first leaves agent users, mailboxes and seats behind in Microsoft 365.

### Teardown log

| Date | Environment | Tenant | Result |
|---|---|---|---|
| 2026-10-27 | `fsifincrime01` | MngEnvMCAP283191 (`2bab7b85-…`) | Replaced by `fsifincrime02` in the E7 tenant. `scripts/teardown.ps1`: no hired instances; hosted agent deleted; resource group deleted; Foundry account and Log Analytics purged; Foundry removed the blueprint and project identities, and the script deleted the one leftover agent identity (verified: 0 `fsifincrime01*` Entra objects). **Manual leftover:** the never-approved "FinCrime Alert Triage" request (Teams app `964829a8-…`) in that tenant's Microsoft 365 admin center: reject or **Permanently delete** it |
