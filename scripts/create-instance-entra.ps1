#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Creates (hires) an autopilot instance directly with the Microsoft Entra Agent ID APIs (Microsoft Graph beta).
.DESCRIPTION
  Use it when the Microsoft 365 admin center can't approve or publish the autopilot blueprint, or Teams has no
  "Create instance". It reproduces the hire flow in the order that worked in the Zava tenant:
    1. Agent identity from the blueprint, with the manager as owner and sponsor.
    2. Agent user (mailbox, Teams presence, org chart) parented by that identity, with the manager.
    3. Frontier seat: the SKU with the AGENT_365_TOOLS plan (for example MICROSOFT_AGENT_365_TIER_3, or
       MICROSOFT_AGENT_365_ROW), which brings Teams and Exchange outside the EEA. Microsoft 365 E5/E7 already on
       the agent user are removed in the same call.
    4. Delegated permission grants for the instance's agent identity, mirroring the blueprint's admin consent
       (Agent Tools MCP scopes, Messaging Bot API) plus Agent 365 observability. Direct creation doesn't add them,
       and without them the instance can't use its Microsoft 365 tools.
  Prerequisite: admin consent on the blueprint (the "Accept permissions" step of the approval wizard). The script
  stops if it's missing. -GrantBlueprintAppRole also grants the blueprint principal the Graph application role
  AgentIdUser.ReadWrite.IdentityParentedBy, which is only needed when the blueprint itself creates agent users.
  Each step reuses what already exists, so the script can be re-run. Without -Apply it only prints the plan.
  Uses the Azure CLI identity (az login as a Global Administrator, or Agent ID Administrator plus User and
  License Administrator). Beta APIs can change. Teams agent settings can show "This agent can't be found" for
  instances created this way, while chat and email work.
.EXAMPLE
  pwsh ./scripts/create-instance-entra.ps1 -Name MiraRetail -Alias miraretail -Manager you@contoso.onmicrosoft.com
  pwsh ./scripts/create-instance-entra.ps1 -Name MiraRetail -Alias miraretail -Manager you@contoso.onmicrosoft.com -Apply
#>
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Alias,
    [Parameter(Mandatory = $true)][string]$Manager,
    [string]$LicenseSku,
    [string]$UsageLocation,
    [string]$BlueprintAppId,
    [string]$SubscriptionId,
    [switch]$GrantBlueprintAppRole,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$agentToolsAppId = "ea9ffc3e-8a23-4a7d-836d-234d7c7565c1"
$observabilityAppId = "9b975845-388f-4429-889e-eab1ef63949c"
$observabilityScope = "Agent365.Observability.OtelWrite"

function Get-AzdValue([string]$Key) {
    Push-Location (Join-Path $PSScriptRoot "..")
    try { $v = (azd env get-value $Key 2>$null | Out-String).Trim() } catch { $v = $null } finally { Pop-Location }
    # azd prints "ERROR: key not found ..." on stdout when the key is missing: accept only a GUID.
    if ($v -match '^[0-9a-fA-F-]{36}$') { return $v }
    return $null
}
if (-not $BlueprintAppId) { $BlueprintAppId = Get-AzdValue "AGENT_BLUEPRINT_CLIENT_ID" }
if (-not $SubscriptionId) { $SubscriptionId = Get-AzdValue "AZURE_SUBSCRIPTION_ID" }
if (-not $BlueprintAppId -or -not $SubscriptionId) { throw "Pass -BlueprintAppId and -SubscriptionId, or run from the repository with a provisioned azd environment." }
if ($Name -notmatch '^[A-Za-z0-9]{1,32}$') { Write-Warning "Agent 365 advises names of up to 32 letters and digits, without spaces or special characters." }

# Bind the token to the subscription's tenant and user (see scripts/common.ps1 for why not --tenant).
$token = az account get-access-token --subscription $SubscriptionId --resource-type ms-graph --query accessToken --output tsv
if ($LASTEXITCODE -ne 0 -or -not $token) { throw "No Microsoft Graph token from the Azure CLI for subscription $SubscriptionId. Run az login." }
$headers = @{ Authorization = "Bearer $token" }

function Graph([string]$Method, [string]$Path, $Body = $null, [string]$Version = "beta") {
    $params = @{ Method = $Method; Uri = "https://graph.microsoft.com/$Version$Path"; Headers = $headers }
    if ($null -ne $Body) { $params.Body = ($Body | ConvertTo-Json -Depth 6); $params.ContentType = "application/json" }
    Invoke-RestMethod @params
}
function Find([string]$Path, [string]$Version = "beta") {
    try { Graph GET $Path -Version $Version }
    catch { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { $null } else { throw } }
}
function Retry([scriptblock]$Action, [string]$What) {
    # New directory objects take a few seconds to replicate before other calls can reference them.
    for ($i = 1; ; $i++) {
        try { return & $Action }
        catch {
            if ($i -ge 8) { throw "$What failed: $($_.Exception.Message) $($_.ErrorDetails.Message)" }
            Write-Host "  $What not possible yet (attempt $i), retrying in 10 s..."
            Start-Sleep -Seconds 10
        }
    }
}
function Get-ServicePrincipal([string]$AppId) {
    (Graph GET "/servicePrincipals?`$filter=appId eq '$AppId'&`$select=id,displayName,appRoles,oauth2PermissionScopes" -Version v1.0).value | Select-Object -First 1
}

# Resolve everything before changing anything.
$managerUser = Graph GET "/users/$([Uri]::EscapeDataString($Manager))?`$select=id,displayName,userPrincipalName" -Version v1.0
$org = (Graph GET "/organization?`$select=id,verifiedDomains,countryLetterCode" -Version v1.0).value | Select-Object -First 1
$domain = ($org.verifiedDomains | Where-Object { $_.isDefault } | Select-Object -First 1).name
if (-not $UsageLocation) { $UsageLocation = if ($org.countryLetterCode) { $org.countryLetterCode } else { "US" } }
$upn = "$Alias@$domain"

$blueprintPrincipal = Get-ServicePrincipal $BlueprintAppId
if (-not $blueprintPrincipal) { throw "No blueprint principal for blueprint $BlueprintAppId in tenant $($org.id)." }

# Instance grants mirror the blueprint's admin consent.
$wantedGrants = [ordered]@{}
foreach ($g in (Graph GET "/oauth2PermissionGrants?`$filter=clientId eq '$($blueprintPrincipal.id)'" -Version v1.0).value) { $wantedGrants[$g.resourceId] = $g.scope.Trim() }
$toolsSp = Get-ServicePrincipal $agentToolsAppId
if (-not $toolsSp -or -not $wantedGrants.Contains($toolsSp.id)) {
    throw "The blueprint has no admin consent for the Agent Tools (Microsoft 365 MCP) scopes yet. Grant it first: Microsoft 365 admin center > Agents > Requests > the blueprint > Accept permissions, or the blueprint's admin consent URL."
}
$observabilitySp = Get-ServicePrincipal $observabilityAppId
if ($observabilitySp -and @($observabilitySp.oauth2PermissionScopes.value) -contains $observabilityScope -and -not $wantedGrants.Contains($observabilitySp.id)) {
    $wantedGrants[$observabilitySp.id] = $observabilityScope
}
$resourceNames = @{}
foreach ($rid in $wantedGrants.Keys) { $resourceNames[$rid] = (Graph GET "/servicePrincipals/$($rid)?`$select=displayName" -Version v1.0).displayName }

$graphSp = Get-ServicePrincipal "00000003-0000-0000-c000-000000000000"
$roleId = ($graphSp.appRoles | Where-Object { $_.value -eq "AgentIdUser.ReadWrite.IdentityParentedBy" }).id
$hasRole = @((Graph GET "/servicePrincipals/$($blueprintPrincipal.id)/appRoleAssignments" -Version v1.0).value |
        Where-Object { $_.appRoleId -eq $roleId -and $_.resourceId -eq $graphSp.id }).Count -gt 0

$skus = @((Graph GET "/subscribedSkus" -Version v1.0).value)
function Free($Sku) { [int]$Sku.prepaidUnits.enabled - [int]$Sku.consumedUnits }
$seat = if ($LicenseSku) { $skus | Where-Object { $_.skuPartNumber -eq $LicenseSku } }
else { $skus | Where-Object { @($_.servicePlans.servicePlanName) -contains "AGENT_365_TOOLS" } | Sort-Object { - (Free $_) } | Select-Object -First 1 }
if (-not $seat) { throw "No Frontier seat SKU (one with the AGENT_365_TOOLS plan) in the tenant. Enroll in Frontier, or pass -LicenseSku." }

$identity = @((Graph GET "/servicePrincipals/microsoft.graph.agentIdentity?`$filter=agentIdentityBlueprintId eq '$BlueprintAppId'&`$select=id,displayName").value |
        Where-Object { $_.displayName -eq $Name }) | Select-Object -First 1
$agentUser = Find "/users/$([Uri]::EscapeDataString($upn))?`$select=id,displayName,userPrincipalName,identityParentId,assignedLicenses"
if ($agentUser -and -not $agentUser.identityParentId) { throw "$upn already exists and is not an agent user. Choose another alias." }
if ($agentUser -and $identity -and $agentUser.identityParentId -ne $identity.id) { throw "$upn belongs to another agent identity ($($agentUser.identityParentId))." }
$heldSkus = @($agentUser.assignedLicenses | ForEach-Object { $_.skuId })
$needsSeat = $heldSkus -notcontains $seat.skuId
$replaced = @($skus | Where-Object { $heldSkus -contains $_.skuId -and $_.skuPartNumber -match "SPE_E5|E7" })

Write-Host "Plan for autopilot instance '$Name' (blueprint $BlueprintAppId, principal $($blueprintPrincipal.id)):"
Write-Host ("  1. Agent identity '{0}', owner and sponsor {1} -> {2}" -f $Name, $managerUser.userPrincipalName, $(if ($identity) { "exists ($($identity.id))" } else { "create" }))
Write-Host ("  2. Agent user {0}, manager {1}, usage location {2} -> {3}" -f $upn, $managerUser.userPrincipalName, $UsageLocation, $(if ($agentUser) { "exists ($($agentUser.id))" } else { "create" }))
Write-Host ("  3. Licence {0} ({1} free) -> {2}{3}" -f $seat.skuPartNumber, (Free $seat), $(if ($needsSeat) { "assign" } else { "already assigned" }), $(if ($replaced) { ", remove " + ($replaced.skuPartNumber -join ", ") } else { "" }))
Write-Host "  4. Delegated grants for the agent identity (AllPrincipals), as on the blueprint:"
foreach ($rid in $wantedGrants.Keys) { Write-Host ("       {0}: {1}" -f $resourceNames[$rid], $wantedGrants[$rid]) }
if ($GrantBlueprintAppRole) { Write-Host ("  +  Blueprint principal: Graph app role AgentIdUser.ReadWrite.IdentityParentedBy -> {0}" -f $(if ($hasRole) { "already granted" } else { "grant" })) }
if ($needsSeat -and (Free $seat) -lt 1) { throw "No free $($seat.skuPartNumber) licence. Offboard an unused instance first." }
if (-not $Apply) { Write-Host "`nPlan only. Re-run with -Apply to make these changes."; return }

if ($GrantBlueprintAppRole -and -not $hasRole) {
    Graph POST "/servicePrincipals/$($blueprintPrincipal.id)/appRoleAssignments" @{ principalId = $blueprintPrincipal.id; resourceId = $graphSp.id; appRoleId = $roleId } -Version v1.0 | Out-Null
    Write-Host "Granted AgentIdUser.ReadWrite.IdentityParentedBy to the blueprint principal."
}

if (-not $identity) {
    $identity = Graph POST "/servicePrincipals/microsoft.graph.agentIdentity" @{
        displayName              = $Name
        agentIdentityBlueprintId = $BlueprintAppId
        "owners@odata.bind"      = @("https://graph.microsoft.com/v1.0/users/$($managerUser.id)")
        "sponsors@odata.bind"    = @("https://graph.microsoft.com/v1.0/users/$($managerUser.id)")
    }
    Write-Host "Created agent identity $($identity.id)"
}

if (-not $agentUser) {
    $agentUser = Retry {
        Graph POST "/users/microsoft.graph.agentUser" @{
            accountEnabled       = $true
            displayName          = $Name
            mailNickname         = $Alias
            userPrincipalName    = $upn
            identityParentId     = $identity.id
            usageLocation        = $UsageLocation
            "manager@odata.bind" = "https://graph.microsoft.com/v1.0/users/$($managerUser.id)"
        }
    } "Creating the agent user"
    Write-Host "Created agent user $($agentUser.id) ($upn)"
}
$currentManager = Find "/users/$($agentUser.id)/manager?`$select=id" -Version v1.0
if (-not $currentManager -or $currentManager.id -ne $managerUser.id) {
    Retry { Graph PUT "/users/$($agentUser.id)/manager/`$ref" @{ "@odata.id" = "https://graph.microsoft.com/v1.0/users/$($managerUser.id)" } -Version v1.0 | Out-Null } "Setting the manager"
    Write-Host "Manager set to $($managerUser.userPrincipalName)"
}

if ($needsSeat) {
    Retry {
        Graph POST "/users/$($agentUser.id)/assignLicense" @{
            addLicenses    = @(@{ skuId = $seat.skuId; disabledPlans = @() })
            removeLicenses = @($replaced | ForEach-Object { $_.skuId })
        } -Version v1.0 | Out-Null
    } "Assigning the licence"
    Write-Host "Assigned $($seat.skuPartNumber)$(if ($replaced) { " and removed $($replaced.skuPartNumber -join ', ')" })"
}

$existingGrants = @((Graph GET "/oauth2PermissionGrants?`$filter=clientId eq '$($identity.id)'" -Version v1.0).value)
foreach ($rid in $wantedGrants.Keys) {
    $wanted = @($wantedGrants[$rid] -split '\s+' | Where-Object { $_ })
    $grant = $existingGrants | Where-Object { $_.resourceId -eq $rid -and $_.consentType -eq "AllPrincipals" } | Select-Object -First 1
    if (-not $grant) {
        Retry { Graph POST "/oauth2PermissionGrants" @{ clientId = $identity.id; consentType = "AllPrincipals"; resourceId = $rid; scope = ($wanted -join " ") } -Version v1.0 | Out-Null } "Granting $($resourceNames[$rid])"
        Write-Host "Granted $($resourceNames[$rid]): $($wanted -join ' ')"
    } else {
        $missing = @($wanted | Where-Object { @($grant.scope -split '\s+') -notcontains $_ })
        if ($missing) {
            Graph PATCH "/oauth2PermissionGrants/$($grant.id)" @{ scope = ((@($grant.scope -split '\s+' | Where-Object { $_ }) + $missing) -join " ") } -Version v1.0 | Out-Null
            Write-Host "Extended $($resourceNames[$rid]) grant with: $($missing -join ' ')"
        }
    }
}

Write-Host "`nDone: '$Name' <$upn>, agent identity $($identity.id), agent user $($agentUser.id), manager $($managerUser.userPrincipalName)."
Write-Host "Teams and the mailbox take a few minutes to provision (mail can bounce 550 5.1.10 meanwhile). Then chat with '$Name' in Teams."
