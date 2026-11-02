#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Tears down one deployed environment of this demo, in the right order.
.DESCRIPTION
  1. Lists hired autopilot instances (Entra agent users) of this environment's blueprint; other teams' instances
     in a shared tenant are ignored. They live in Microsoft 365, not in Azure, so delete them in the Microsoft 365
     admin center first (the script stops unless -Force).
  2. Deletes the hosted agent through the Foundry data plane (versions, sessions, endpoint).
  3. Runs `azd down --force --purge` for the environment (resource group, purged Foundry account).
  4. Verifies the resource group is gone and reports leftover Entra agent identity objects created for
     this environment; -DeleteEntraObjects removes them.
  5. Prints the remaining Microsoft 365 admin center step for the published blueprint.
  The Azure CLI default subscription is switched to the environment's subscription while the script runs
  (azd uses the az CLI identity) and restored afterwards.
.EXAMPLE
  pwsh ./scripts/teardown.ps1 -Environment <azd-env-name>
  pwsh ./scripts/teardown.ps1 -Environment <azd-env-name> -DeleteEntraObjects
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Environment,
    [switch]$Force,
    [switch]$DeleteEntraObjects
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
$previousDefault = az account show --query id --output tsv 2>$null
try {
    $values = @{}
    azd env get-values -e $Environment | ForEach-Object {
        if ($_ -match '^([A-Za-z0-9_]+)="?(.*?)"?$') { $values[$Matches[1]] = $Matches[2] }
    }
    if ($LASTEXITCODE -ne 0 -or -not $values["AZURE_SUBSCRIPTION_ID"]) { throw "azd environment '$Environment' not found or incomplete." }
    foreach ($key in $values.Keys) { Set-Item -Path "Env:$key" -Value $values[$key] }
    . "$PSScriptRoot/common.ps1"

    $subscriptionId = $values["AZURE_SUBSCRIPTION_ID"]
    $resourceGroup = $values["AZURE_RESOURCE_GROUP"]
    $account = az account show --subscription $subscriptionId --query "{user:user.name, tenant:tenantId}" --output json | ConvertFrom-Json
    if (-not $account) { throw "The Azure CLI has no access to subscription $subscriptionId. Run az login --tenant <tenant-id>." }
    Write-Host "Tearing down '$Environment': subscription $subscriptionId, resource group $resourceGroup, as $($account.user)"
    az account set --subscription $subscriptionId

    $graphToken = az account get-access-token --subscription $subscriptionId --resource-type ms-graph --query accessToken --output tsv
    $graph = @{ Authorization = "Bearer $graphToken" }

    # 1. Hired instances live in Microsoft 365 and survive Azure teardown.
    $agentUsers = @()
    try { $agentUsers = @((Invoke-RestMethod -Headers $graph -Uri "https://graph.microsoft.com/beta/users/microsoft.graph.agentUser?`$select=displayName,userPrincipalName,createdDateTime,agentIdentityBlueprintId").value) } catch { Write-Warning "Could not list agent users: $($_.Exception.Message)" }
    # Shared tenants also host other teams' autopilots. Only instances that may come from this environment's
    # blueprint (same blueprint ID, or none reported) block the teardown.
    $ourBlueprints = @($values["AGENT_BLUEPRINT_CLIENT_ID"], $values["BID_DESK_AGENT_BLUEPRINT_CLIENT_ID"]) | Where-Object { $_ }
    if ($ourBlueprints.Count -gt 0) {
        $others = @($agentUsers | Where-Object { $_.agentIdentityBlueprintId -and $ourBlueprints -notcontains $_.agentIdentityBlueprintId })
        if ($others.Count -gt 0) { Write-Host "Ignoring $($others.Count) agent user(s) hired from other blueprints in this tenant." }
        $agentUsers = @($agentUsers | Where-Object { -not $_.agentIdentityBlueprintId -or $ourBlueprints -contains $_.agentIdentityBlueprintId })
    }
    if ($agentUsers.Count -gt 0) {
        Write-Warning "Hired autopilot instances of this blueprint exist (delete them in the Microsoft 365 admin center first):"
        $agentUsers | ForEach-Object { Write-Warning "  $($_.displayName) <$($_.userPrincipalName)> created $($_.createdDateTime)" }
        if (-not $Force) { throw "Stopping. Delete the instances, or re-run with -Force." }
    } else {
        Write-Host "No hired instances (agent users) of this blueprint in the tenant."
    }

    # 2. Hosted agents (FinCrime and, when deployed, the RFP Bid Desk).
    $endpoint = $values["AZURE_AI_PROJECT_ENDPOINT"]
    $agentNames = @($values["AGENT_NAME"], $values["BID_DESK_AGENT_NAME"]) | Where-Object { $_ }
    foreach ($agentName in $agentNames) {
        if (-not $endpoint) { break }
        $token = Get-FoundryAccessToken
        try {
            Invoke-RestMethod -Method Delete -Headers @{ Authorization = "Bearer $token" } -Uri "$($endpoint.TrimEnd('/'))/agents/$agentName`?api-version=v1" | Out-Null
            Write-Host "Deleted hosted agent $agentName."
        } catch {
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            if ($status -eq 404) { Write-Host "Hosted agent $agentName not found (already deleted)." }
            else { Write-Warning "Deleting the hosted agent returned HTTP ${status}: $($_.Exception.Message). Continuing with azd down." }
        }
    }

    # 3. Azure resources.
    $env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"
    azd down -e $Environment --force --purge
    if ($LASTEXITCODE -ne 0) { throw "azd down failed with exit code $LASTEXITCODE." }

    # 4. Verify and report leftovers.
    $exists = az group exists --subscription $subscriptionId --name $resourceGroup
    Write-Host "Resource group $resourceGroup exists: $exists"
    $prefix = "$($values['ACCOUNT_NAME'])-$($values['PROJECT_NAME'])-"
    $leftovers = @()
    foreach ($kind in @("applications/microsoft.graph.agentIdentityBlueprint", "servicePrincipals/microsoft.graph.agentIdentityBlueprintPrincipal", "servicePrincipals/microsoft.graph.agentIdentity")) {
        try {
            $found = (Invoke-RestMethod -Headers $graph -Uri "https://graph.microsoft.com/beta/$kind`?`$select=id,displayName&`$top=999").value | Where-Object { $_.displayName -like "$prefix*" }
            $leftovers += @($found | ForEach-Object { [pscustomobject]@{ Kind = $kind.Split("/")[0]; Id = $_.id; DisplayName = $_.displayName } })
        } catch { Write-Warning "Could not list ${kind}: $($_.Exception.Message)" }
    }
    if ($leftovers.Count -eq 0) {
        Write-Host "No leftover Entra agent identity objects for prefix '$prefix'."
    } else {
        Write-Host "Leftover Entra agent identity objects for '$prefix':"
        $leftovers | Format-Table -AutoSize | Out-String -Width 220 | Write-Host
        if ($DeleteEntraObjects) {
            # Service principals first (agent identities, then blueprint principals), then blueprint applications.
            foreach ($item in ($leftovers | Sort-Object { if ($_.Kind -eq "applications") { 1 } else { 0 } })) {
                try {
                    Invoke-RestMethod -Method Delete -Headers $graph -Uri "https://graph.microsoft.com/beta/$($item.Kind)/$($item.Id)" | Out-Null
                    Write-Host "Deleted $($item.Kind) $($item.DisplayName)"
                } catch {
                    $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
                    if ($status -eq 404) { Write-Host "Already gone: $($item.DisplayName)" } else { Write-Warning "Could not delete $($item.DisplayName) (HTTP $status): $($_.Exception.Message)" }
                }
            }
        } else {
            Write-Host "Re-run with -DeleteEntraObjects to remove them, or delete them in the Entra admin center (Agent ID)."
        }
    }

    # 5. Microsoft 365 side.
    Write-Host ""
    Write-Host "Remaining manual step (Microsoft 365 admin center, Global or AI Administrator):"
    Write-Host "  Agents > All agents: find '$(Get-EnvOrDefault 'AGENT_DISPLAY_NAME' 'FinCrime Alert Triage')' (Teams app $($values['PUBLISHED_TEAMS_APP_ID'])) and select"
    Write-Host "  'Permanently delete' (or reject it on the Requests tab if it was never approved)."
    if ($values["BID_DESK_AGENT_NAME"]) {
        Write-Host "  Do the same for 'RFP Bid Desk' (Teams app $($values['BID_DESK_PUBLISHED_TEAMS_APP_ID']))."
    }
}
finally {
    if ($previousDefault) { az account set --subscription $previousDefault 2>$null }
    Pop-Location
}
