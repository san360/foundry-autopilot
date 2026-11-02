#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Gives one hired RFP Bid Desk instance read access to its own bid team's answer library, and nothing else.
.DESCRIPTION
  Assigns "Search Index Data Reader" at the scope of ONE index (.../searchServices/<svc>/indexes/<index>) to the
  instance's own identity, so Azure, not the prompt, decides which library each instance can read: asking
  PublicSectorBids for banking answers returns HTTP 403 from Azure AI Search.
  The identity depends on how the agent gets its Search token (SEARCH_TOKEN_FLOW on the agent version):
    agentIdentity (default): the instance's agent identity (service principal), autonomous app-only token.
                             No OAuth consent needed. Covers SEARCH_TOKEN_FLOW agent_identity and session_identity.
    agentUser:               the instance's agent user (its own user account), delegated token. Also needs a
                             delegated grant of Azure AI Search user_impersonation on the agent identity, which
                             this script adds (as create-instance-entra.ps1 does for the Microsoft 365 tools).
    both:                    both of the above (use with "/whoami probe" to compare the flows).
  It also warns when the instance or the container's default identity holds a Search data role at a wider scope,
  which would break the isolation. Index-scope assignments can't be made in the Azure portal or Bicep (indexes are
  not ARM resources); the Azure CLI is used. Without -Apply it only prints the plan. -Revoke removes the grant.
  Needs: Owner or User Access Administrator on the Search service; for agentUser also Agent ID Administrator or
  Cloud Application Administrator (delegated grants).
.EXAMPLE
  pwsh ./scripts/grant-bid-team-access.ps1 -Instance BankingBids -Team banking
  pwsh ./scripts/grant-bid-team-access.ps1 -Instance BankingBids -Team banking -Apply
  pwsh ./scripts/grant-bid-team-access.ps1 -Instance PublicSectorBids -Team publicsector -Flow both -Apply
#>
param(
    [Parameter(Mandatory = $true)][string]$Instance,
    [Parameter(Mandatory = $true)][string]$Team,
    [ValidateSet("agentIdentity", "agentUser", "both")][string]$Flow,
    [string]$Index,
    [string]$BlueprintAppId,
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$SearchServiceName,
    [switch]$Revoke,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$searchAppId = "880da380-985e-4198-81b9-e05b1cc53158"   # Azure AI Search (first-party application)
$readerRole = "Search Index Data Reader"
$searchDataRoles = @("Search Index Data Reader", "Search Index Data Contributor", "Search Service Contributor", "Owner", "Contributor")

function Get-AzdValue([string]$Key) {
    Push-Location (Join-Path $PSScriptRoot "..")
    try { $v = (azd env get-value $Key 2>$null | Out-String).Trim() } catch { $v = $null } finally { Pop-Location }
    # azd prints "ERROR: key not found ..." on stdout when the key is missing.
    if ($v -and $v -notmatch '^ERROR') { return $v }
    return $null
}
if (-not $BlueprintAppId) { $BlueprintAppId = Get-AzdValue "BID_DESK_AGENT_BLUEPRINT_CLIENT_ID" }
if (-not $SubscriptionId) { $SubscriptionId = Get-AzdValue "AZURE_SUBSCRIPTION_ID" }
if (-not $ResourceGroup) { $ResourceGroup = Get-AzdValue "AZURE_RESOURCE_GROUP" }
if (-not $SearchServiceName) { $SearchServiceName = Get-AzdValue "SEARCH_SERVICE_NAME" }
if (-not $Flow) {
    $configured = Get-AzdValue "BID_DESK_SEARCH_TOKEN_FLOW"
    $Flow = if ($configured -eq "agent_user") { "agentUser" } else { "agentIdentity" }
}
if (-not $Index) {
    $teams = @{ banking = "bids-banking"; publicsector = "bids-publicsector" }
    $bidTeams = Get-AzdValue "BID_TEAMS"
    if ($bidTeams) { ($bidTeams | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $teams[$_.Name.ToLowerInvariant()] = $_.Value.index } }
    $Index = $teams[$Team.ToLowerInvariant()]
    if (-not $Index) { throw "Unknown team '$Team'. Known: $($teams.Keys -join ', '). Or pass -Index." }
}
foreach ($pair in @(@("BlueprintAppId", $BlueprintAppId), @("SubscriptionId", $SubscriptionId), @("ResourceGroup", $ResourceGroup), @("SearchServiceName", $SearchServiceName))) {
    if (-not $pair[1]) { throw "Pass -$($pair[0]) or run from the repository with a provisioned azd environment (ENABLE_BID_DESK=true)." }
}

$token = az account get-access-token --subscription $SubscriptionId --resource-type ms-graph --query accessToken --output tsv
if ($LASTEXITCODE -ne 0 -or -not $token) { throw "No Microsoft Graph token from the Azure CLI for subscription $SubscriptionId. Run az login." }
$graphHeaders = @{ Authorization = "Bearer $token" }
function Graph([string]$Method, [string]$Path, $Body = $null, [string]$Version = "beta") {
    $params = @{ Method = $Method; Uri = "https://graph.microsoft.com/$Version$Path"; Headers = $graphHeaders }
    if ($null -ne $Body) { $params.Body = ($Body | ConvertTo-Json -Depth 6); $params.ContentType = "application/json" }
    Invoke-RestMethod @params
}

# Resolve the instance's identities (created when the instance was hired from the bid desk blueprint).
$identities = @((Graph GET "/servicePrincipals/microsoft.graph.agentIdentity?`$filter=agentIdentityBlueprintId eq '$BlueprintAppId'&`$select=id,appId,displayName").value)
$identity = $identities | Where-Object { $_.displayName -eq $Instance } | Select-Object -First 1
if (-not $identity) {
    $identity = $identities | Where-Object { $_.displayName -like "*$Instance*" } | Select-Object -First 1
}
if (-not $identity) {
    throw "No agent identity named '$Instance' for blueprint $BlueprintAppId. Hired instances: $(($identities | ForEach-Object displayName) -join ', ')"
}
$agentUser = $null
if ($Flow -ne "agentIdentity") {
    $agentUser = @((Graph GET "/users/microsoft.graph.agentUser?`$select=id,displayName,userPrincipalName,identityParentId&`$top=999").value) |
        Where-Object { $_.identityParentId -eq $identity.id } | Select-Object -First 1
    if (-not $agentUser) { throw "Agent identity $($identity.id) has no agent user yet (the hire may still be provisioning)." }
}

$serviceScope = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Search/searchServices/$SearchServiceName"
$indexScope = "$serviceScope/indexes/$Index"
$principals = @()
if ($Flow -ne "agentUser") { $principals += [pscustomobject]@{ Kind = "agent identity"; Id = $identity.id; Type = "ServicePrincipal"; Name = $identity.displayName } }
if ($agentUser) { $principals += [pscustomobject]@{ Kind = "agent user"; Id = $agentUser.id; Type = "User"; Name = $agentUser.userPrincipalName } }

$searchSp = $null
$grant = $null
if ($agentUser) {
    $searchSp = (Graph GET "/servicePrincipals?`$filter=appId eq '$searchAppId'&`$select=id,displayName" -Version v1.0).value | Select-Object -First 1
    if ($searchSp) {
        $grant = @((Graph GET "/oauth2PermissionGrants?`$filter=clientId eq '$($identity.id)' and resourceId eq '$($searchSp.id)'" -Version v1.0).value) | Select-Object -First 1
    }
}

$verb = if ($Revoke) { "Remove" } else { "Assign" }
Write-Host "Plan for '$Instance' -> index '$Index' (flow $Flow):"
foreach ($p in $principals) { Write-Host "  $verb '$readerRole' for the $($p.Kind) $($p.Name) ($($p.Id)) at $indexScope" }
if ($agentUser -and -not $Revoke) {
    $state = if ($grant -and (@($grant.scope -split '\s+') -contains "user_impersonation")) { "already granted" } elseif ($searchSp) { "grant" } else { "create the Azure AI Search service principal, then grant" }
    Write-Host "  Delegated grant: Azure AI Search user_impersonation for agent identity $($identity.id) -> $state"
}

# Isolation check: any Search data role at the service or a wider scope would let the instance read every library.
$defaultInstance = Get-AzdValue "BID_DESK_AGENT_INSTANCE_CLIENT_ID"
$checks = @($principals | ForEach-Object { @{ Label = "$($_.Kind) of $Instance"; Assignee = $_.Id } })
if ($defaultInstance) { $checks += @{ Label = "container default instance identity"; Assignee = $defaultInstance } }
foreach ($check in $checks) {
    $wide = @(az role assignment list --assignee $check.Assignee --all --subscription $SubscriptionId --query "[?roleDefinitionName!=null]" --output json 2>$null | ConvertFrom-Json) |
        Where-Object { $searchDataRoles -contains $_.roleDefinitionName -and $_.scope -notlike "$serviceScope/indexes/*" -and $serviceScope.StartsWith($_.scope, [StringComparison]::OrdinalIgnoreCase) }
    foreach ($w in $wide) { Write-Warning "The $($check.Label) has '$($w.roleDefinitionName)' at $($w.scope): that breaks per-team isolation." }
}

if (-not $Apply) { Write-Host "`nPlan only. Re-run with -Apply to make these changes."; return }

foreach ($p in $principals) {
    if ($Revoke) {
        az role assignment delete --assignee $p.Id --role $readerRole --scope $indexScope --subscription $SubscriptionId | Out-Null
        Write-Host "Removed '$readerRole' for the $($p.Kind) at $indexScope."
        continue
    }
    $out = az role assignment create --assignee-object-id $p.Id --assignee-principal-type $p.Type --role $readerRole --scope $indexScope --subscription $SubscriptionId 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0) { Write-Host "Assigned '$readerRole' to the $($p.Kind) at $indexScope." }
    elseif ($out -match "RoleAssignmentExists") { Write-Host "'$readerRole' already assigned to the $($p.Kind)." }
    else { throw "Role assignment failed for the $($p.Kind): $out" }
}

if ($agentUser -and -not $Revoke) {
    if (-not $searchSp) {
        $searchSp = Graph POST "/servicePrincipals" @{ appId = $searchAppId } -Version v1.0
        Write-Host "Created the Azure AI Search service principal in the tenant."
    }
    if (-not $grant) {
        Graph POST "/oauth2PermissionGrants" @{ clientId = $identity.id; consentType = "AllPrincipals"; resourceId = $searchSp.id; scope = "user_impersonation" } -Version v1.0 | Out-Null
        Write-Host "Granted Azure AI Search user_impersonation to agent identity $($identity.id)."
    } elseif (@($grant.scope -split '\s+') -notcontains "user_impersonation") {
        Graph PATCH "/oauth2PermissionGrants/$($grant.id)" @{ scope = "$($grant.scope) user_impersonation".Trim() } -Version v1.0 | Out-Null
        Write-Host "Extended the Azure AI Search grant with user_impersonation."
    }
}

Write-Host "`nDone. Azure RBAC on the Search data plane can take a few minutes to apply; then ask $Instance '/whoami probe' in Teams."
