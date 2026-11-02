#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Wires up RFP Bid Desk instances after they are hired in Teams: ID routing, per-index Search access, new version.
.DESCRIPTION
  Teams activities carry only an instance's IDs, not its name, and every hire gets new IDs. After hiring (or
  re-hiring) BankingBids / PublicSectorBids through Teams > Apps > Agents for your team > RFP Bid Desk > Create
  instance, this script:
    1. Finds every instance of the bid desk blueprint (agent identity + agent user) and its team from its name
       (keywords in BID_TEAM_RULES, default banking / publicsector).
    2. Rebuilds BID_TEAM_RULES: the name keywords plus each current instance's agent-user and agent-identity IDs
       (IDs of deleted instances are dropped), and BID_COLLEAGUES (agent-user ID -> instance name, so instances
       recognise each other's messages by object ID; doc 17), and saves both to the azd environment.
    3. Grants each instance Search Index Data Reader on its own team's index (scripts/grant-bid-team-access.ps1).
    4. Rolls out a new bid desk version with the new mapping (scripts/deploy-bid-desk-agent.ps1 -SkipPublish).
  Without -Apply it only prints the plan. Needs Owner (activate PIM in Zava) and Graph read of agent identities.
.EXAMPLE
  pwsh ./scripts/sync-bid-desk-instances.ps1
  pwsh ./scripts/sync-bid-desk-instances.ps1 -Apply
#>
param(
    [string]$Environment,
    [switch]$SkipDeploy,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$root = Join-Path $PSScriptRoot ".."
Push-Location $root
try {
    $envArgs = if ($Environment) { @("-e", $Environment) } else { @() }
    $values = @{}
    foreach ($line in (azd env get-values @envArgs)) {
        if ($line -match '^([A-Za-z0-9_]+)="?(.*?)"?$') { $values[$Matches[1]] = $Matches[2] -replace '\\"', '"' }
    }
    $blueprint = $values["BID_DESK_AGENT_BLUEPRINT_CLIENT_ID"]
    $subscription = $values["AZURE_SUBSCRIPTION_ID"]
    if (-not $blueprint) { throw "BID_DESK_AGENT_BLUEPRINT_CLIENT_ID is not set: deploy the bid desk first (ENABLE_BID_DESK=true)." }

    $teams = @{ banking = "bids-banking"; publicsector = "bids-publicsector" }
    if ($values["BID_TEAMS"]) { ($values["BID_TEAMS"] | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $teams[$_.Name.ToLowerInvariant()] = $_.Value.index } }
    $keywords = [ordered]@{ banking = "banking"; financial = "banking"; publicsector = "publicsector"; government = "publicsector" }
    if ($values["BID_TEAM_RULES"]) {
        $keywords = [ordered]@{}
        ($values["BID_TEAM_RULES"] | ConvertFrom-Json).PSObject.Properties |
            Where-Object { $_.Name -notmatch '^[0-9a-fA-F-]{36}$' } |
            ForEach-Object { $keywords[$_.Name.ToLowerInvariant()] = [string]$_.Value }
    }

    $token = az account get-access-token --subscription $subscription --resource-type ms-graph --query accessToken --output tsv
    if ($LASTEXITCODE -ne 0 -or -not $token) { throw "No Microsoft Graph token from the Azure CLI. Run az login." }
    $headers = @{ Authorization = "Bearer $token" }
    $identities = @((Invoke-RestMethod -Headers $headers -Uri "https://graph.microsoft.com/beta/servicePrincipals/microsoft.graph.agentIdentity?`$filter=agentIdentityBlueprintId eq '$blueprint'&`$select=id,appId,displayName").value)
    $users = @((Invoke-RestMethod -Headers $headers -Uri "https://graph.microsoft.com/beta/users/microsoft.graph.agentUser?`$select=id,displayName,userPrincipalName,identityParentId&`$top=999").value)

    $rules = [ordered]@{}
    foreach ($k in $keywords.Keys) { $rules[$k] = $keywords[$k] }
    $colleagues = [ordered]@{}
    $instances = @()
    foreach ($identity in $identities) {
        # The default instance identity is the shared container credential: never map it or give it data access.
        if ($identity.appId -eq $values["BID_DESK_AGENT_INSTANCE_CLIENT_ID"]) { continue }
        $user = $users | Where-Object { $_.identityParentId -eq $identity.id } | Select-Object -First 1
        $haystack = (($identity.displayName, $user.userPrincipalName) -join " ").ToLowerInvariant() -replace '[^a-z0-9 ]', ''
        $team = $null
        foreach ($k in ($keywords.Keys | Sort-Object Length -Descending)) { if ($haystack.Contains($k)) { $team = $keywords[$k]; break } }
        $instances += [pscustomobject]@{ Name = $identity.displayName; Team = $team; Identity = $identity.appId; User = $user.id; Upn = $user.userPrincipalName }
        if ($team) {
            $rules[$identity.appId] = $team
            if ($user) { $rules[$user.id] = $team; $colleagues[$user.id] = $identity.displayName }
        }
    }
    $rulesJson = $rules | ConvertTo-Json -Compress
    $colleaguesJson = if ($colleagues.Count) { $colleagues | ConvertTo-Json -Compress } else { "" }

    Write-Host "Bid desk instances (blueprint $blueprint):"
    if (-not $instances) { Write-Host "  none yet: hire them in Teams > Apps > Agents for your team > RFP Bid Desk > Create instance." }
    $instances | Format-Table Name, Team, Upn, User, Identity -AutoSize | Out-String -Width 220 | Write-Host
    $unmapped = @($instances | Where-Object { -not $_.Team })
    if ($unmapped) { Write-Warning "No team for: $($unmapped.Name -join ', '). Put banking or publicsector in the name, or add a keyword to BID_TEAM_RULES." }
    $pending = @($instances | Where-Object { $_.Team -and -not $_.User })
    if ($pending) { Write-Warning "No agent user yet for: $($pending.Name -join ', ') (the hire may still be provisioning). Re-run in a few minutes." }
    Write-Host "BID_TEAM_RULES -> $rulesJson"
    Write-Host "BID_COLLEAGUES -> $colleaguesJson"
    if (-not $Apply) { Write-Host "`nPlan only. Re-run with -Apply."; return }

    azd env set BID_TEAM_RULES $rulesJson @envArgs | Out-Null
    azd env set BID_COLLEAGUES $colleaguesJson @envArgs | Out-Null
    foreach ($i in $instances | Where-Object { $_.Team -and $_.User }) {
        Write-Host "===== Search access for $($i.Name) -> $($teams[$i.Team]) ====="
        & "$PSScriptRoot/grant-bid-team-access.ps1" -Instance $i.Name -Team $i.Team -Apply
    }

    if (-not $SkipDeploy) {
        Write-Host "===== New bid desk version with the updated mapping ====="
        $values["BID_TEAM_RULES"] = $rulesJson
        $values["BID_COLLEAGUES"] = $colleaguesJson
        $saved = @{}
        foreach ($k in $values.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $values[$k]) }
        try { & "$PSScriptRoot/deploy-bid-desk-agent.ps1" -SkipPublish }
        finally { foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) } }
    }
    Write-Host "`nDone. In Teams: add the instances to their chats (for example 'Woodgrove bid team'), then try '/whoami probe'."
}
finally { Pop-Location }
