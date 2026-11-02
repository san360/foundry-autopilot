#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Read-only health check of the deployed FinCrime autopilot (run before every demo).
.DESCRIPTION
  Uses the active azd environment to verify: hosted agent state and latest version, container image,
  endpoint protocol and authorization schemes, digital-worker type, model deployment, the Entra agent
  identity blueprint and (optionally) a short live scenario run against the model.
.EXAMPLE
  pwsh ./scripts/smoke-test.ps1            # configuration checks
  pwsh ./scripts/smoke-test.ps1 -RunEval   # plus two live model scenarios (~1 minute, a few cents)
#>
param([switch]$RunEval)

$ErrorActionPreference = "Continue"
. "$PSScriptRoot/common.ps1"

Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    azd env get-values | ForEach-Object {
        if ($_ -match '^([A-Za-z0-9_]+)="?(.*?)"?$') { Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2] }
    }
} finally { Pop-Location }

$results = [System.Collections.Generic.List[object]]::new()
function Add-Result([string]$Check, [bool]$Ok, [string]$Detail) {
    $results.Add([pscustomobject]@{ Check = $Check; Status = $(if ($Ok) { "OK" } else { "FAIL" }); Detail = $Detail })
}
function Add-Info([string]$Check, [string]$Detail) {
    $results.Add([pscustomobject]@{ Check = $Check; Status = "INFO"; Detail = $Detail })
}

$endpoint = $env:AZURE_AI_PROJECT_ENDPOINT
$agentName = $env:AGENT_NAME
$token = Get-FoundryAccessToken
$headers = @{ Authorization = "Bearer $token"; "Foundry-Features" = "HostedAgents=V1Preview,DigitalWorker=V1Preview" }

try {
    $agent = Invoke-RestMethod -Headers $headers -Uri "$endpoint/agents/$agentName`?api-version=2025-11-15-preview"
    $latest = $agent.versions.latest
    Add-Result "Hosted agent enabled" ($agent.state -eq "enabled") "$($agent.id) state=$($agent.state)"
    Add-Result "Latest version active" ($latest.status -eq "active") "version $($latest.version) status=$($latest.status)"
    Add-Result "Digital worker (autopilot-capable)" ($agent.digital_worker_type -eq "m365") "digital_worker_type=$($agent.digital_worker_type)"
    Add-Result "Activity protocol endpoint" ($agent.agent_endpoint.protocols -contains "activity") (($agent.agent_endpoint.protocols) -join ",")
    $schemes = @($agent.agent_endpoint.authorization_schemes | ForEach-Object { $_.type })
    Add-Result "Endpoint auth schemes" ($schemes.Count -gt 0) ($schemes -join ",")
    Add-Result "Image pinned" ([bool]$latest.definition.image) $latest.definition.image
    Add-Result "Model env var" ($latest.definition.environment_variables.ModelDeployment -eq $env:MODEL_NAME) "ModelDeployment=$($latest.definition.environment_variables.ModelDeployment)"
    Add-Result "Sender allow-list configured" ([bool]$latest.definition.environment_variables.ALLOWED_SENDER_DOMAINS) "$($latest.definition.environment_variables.ALLOWED_SENDER_DOMAINS)"
    $blueprintClientId = $latest.blueprint.client_id
} catch {
    Add-Result "Hosted agent reachable" $false $_.Exception.Message
}

$deployment = az cognitiveservices account deployment show --subscription (Get-DeploymentSubscriptionId) -g $env:RESOURCE_GROUP -n $env:ACCOUNT_NAME --deployment-name $env:MODEL_NAME --query "{state:properties.provisioningState, capacity:sku.capacity}" -o json 2>$null | ConvertFrom-Json
Add-Result "Model deployment" ($deployment.state -eq "Succeeded") "$($env:MODEL_NAME) state=$($deployment.state) capacity=$($deployment.capacity)K TPM"

if ($blueprintClientId) {
    $graph = az account get-access-token --subscription (Get-DeploymentSubscriptionId) --resource-type ms-graph --query accessToken -o tsv
    try {
        $bp = Invoke-RestMethod -Headers @{ Authorization = "Bearer $graph" } -Uri "https://graph.microsoft.com/beta/applications(appId='$blueprintClientId')?`$select=displayName"
        Add-Result "Entra agent identity blueprint" ($bp.'@odata.type' -eq "#microsoft.graph.agentIdentityBlueprint") $bp.displayName
    } catch { Add-Result "Entra agent identity blueprint" $false $_.Exception.Message }
}
Add-Result "Published to Microsoft 365" ([bool]$env:PUBLISHED_APP_VERSION) "appVersion=$($env:PUBLISHED_APP_VERSION) teamsAppId=$($env:PUBLISHED_TEAMS_APP_ID) (approval is a human step in the M365 admin center)"

# Hired instances = Entra agent users (one per instance), with their manager and licences.
$graphToken = az account get-access-token --subscription (Get-DeploymentSubscriptionId) --resource-type ms-graph --query accessToken -o tsv
$graphHeaders = @{ Authorization = "Bearer $graphToken" }
try {
    $skuNames = @{}
    (Invoke-RestMethod -Headers $graphHeaders -Uri "https://graph.microsoft.com/v1.0/subscribedSkus").value | ForEach-Object { $skuNames[$_.skuId] = $_.skuPartNumber }
    $agentUsers = @((Invoke-RestMethod -Headers $graphHeaders -Uri "https://graph.microsoft.com/beta/users/microsoft.graph.agentUser?`$select=id,displayName,userPrincipalName,createdDateTime,assignedLicenses,agentIdentityBlueprintId").value)
    # Shared tenants also host other teams' autopilots: keep the instances hired from this environment's blueprint.
    $ourBlueprint = if ($blueprintClientId) { $blueprintClientId } else { $env:AGENT_BLUEPRINT_CLIENT_ID }
    $otherAgentUsers = @()
    if ($ourBlueprint) {
        $otherAgentUsers = @($agentUsers | Where-Object { $_.agentIdentityBlueprintId -and $_.agentIdentityBlueprintId -ne $ourBlueprint })
        $agentUsers = @($agentUsers | Where-Object { $_.agentIdentityBlueprintId -eq $ourBlueprint })
    }
    if ($agentUsers.Count -eq 0) {
        Add-Info "Hired instances (agent users)" "none yet - approve the blueprint, then Create instance (docs/08 Step 5)"
    }
    foreach ($agentUser in $agentUsers) {
        $managerName = "(no manager)"
        try { $managerName = (Invoke-RestMethod -Headers $graphHeaders -Uri "https://graph.microsoft.com/v1.0/users/$($agentUser.id)/manager?`$select=displayName").displayName } catch { }
        $licences = ($agentUser.assignedLicenses | ForEach-Object { if ($skuNames.ContainsKey($_.skuId)) { $skuNames[$_.skuId] } else { $_.skuId } }) -join ", "
        Add-Info "Hired instance $($agentUser.displayName)" "$($agentUser.userPrincipalName) | manager: $managerName | licences: $licences | created $($agentUser.createdDateTime)"
    }
    if ($otherAgentUsers.Count -gt 0) {
        Add-Info "Other autopilots in the tenant" "$($otherAgentUsers.Count) agent user(s) hired from other blueprints (not part of this deployment)"
    }
} catch {
    Add-Info "Hired instances (agent users)" "could not query Microsoft Graph: $($_.Exception.Message)"
}

if ($RunEval) {
    $python = Join-Path (Split-Path -Parent $PSScriptRoot) ".venv/Scripts/python.exe"
    if (-not (Test-Path $python)) { $python = "python" }
    & $python (Join-Path (Split-Path -Parent $PSScriptRoot) "eval/run_scenarios.py") --endpoint $endpoint --model $env:MODEL_NAME --subscription (Get-DeploymentSubscriptionId) --only triage_structuring tipping_off_refusal
    Add-Result "Live scenarios (structuring, tipping-off)" ($LASTEXITCODE -eq 0) "see eval/results"
}

$results | Format-Table -AutoSize -Wrap | Out-String -Width 220 | Write-Host
if ($results.Status -contains "FAIL") { exit 1 }
