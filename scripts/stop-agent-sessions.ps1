#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Moves every conversation to the agent's latest version by deleting sessions pinned to older versions.
.DESCRIPTION
  Hosted-agent sessions stay pinned to the agent version they started on, also after a stop, and Microsoft 365
  conversations (Teams chats, email threads) keep resuming the same session. The sessions list API doesn't return
  every session either (Teams and email sessions were missing in the Zava tenant), so the script also takes the
  session IDs that Application Insights recorded over the last -LookbackDays days. Each session pinned to a version
  other than -KeepVersion (default: the latest version) is deleted; the conversation's next message starts a fresh
  session on the latest version. The post-provision hook runs it after creating a new agent version.
.EXAMPLE
  pwsh ./scripts/stop-agent-sessions.ps1
#>
param(
    [string]$ProjectEndpoint = $env:AZURE_AI_PROJECT_ENDPOINT,
    [string]$AgentName = $env:AGENT_NAME,
    [string]$ApplicationInsightsResourceId = $env:APPLICATIONINSIGHTS_RESOURCE_ID,
    [string]$KeepVersion,
    [int]$LookbackDays = 30
)

$ErrorActionPreference = "Stop"

. "$PSScriptRoot/common.ps1"

if ([string]::IsNullOrWhiteSpace($ProjectEndpoint)) { throw "AZURE_AI_PROJECT_ENDPOINT is required." }
if ([string]::IsNullOrWhiteSpace($AgentName)) { throw "AGENT_NAME is required." }

$headers = @{
    "Accept"           = "application/json"
    "Authorization"    = "Bearer $(Get-FoundryAccessToken)"
    "Foundry-Features" = "HostedAgents=V1Preview"
}
function Get-StatusCode($ErrorRecord) {
    if ($ErrorRecord.Exception.Response) { return [int]$ErrorRecord.Exception.Response.StatusCode }
    return 0
}

$agentUrl = "$($ProjectEndpoint.TrimEnd('/'))/agents/$([Uri]::EscapeDataString($AgentName))"
try {
    $agent = Invoke-RestMethod -Uri "${agentUrl}?api-version=2025-11-15-preview" -Method Get -Headers $headers
}
catch {
    if ((Get-StatusCode $_) -eq 404) { Write-Host "Agent '$AgentName' does not exist yet; no sessions to retire."; return }
    throw
}
if ([string]::IsNullOrWhiteSpace($KeepVersion)) { $KeepVersion = [string]$agent.versions.latest.version }
$sessionsUrl = "$agentUrl/endpoint/sessions"

# 1. Session IDs from the sessions API.
$sessionIds = [System.Collections.Generic.HashSet[string]]::new()
$paginationToken = $null
do {
    $listUrl = "${sessionsUrl}?api-version=v1&limit=100"
    if (-not [string]::IsNullOrWhiteSpace($paginationToken)) {
        $listUrl += "&pagination_token=$([Uri]::EscapeDataString($paginationToken))"
    }
    $response = Invoke-RestMethod -Uri $listUrl -Method Get -Headers $headers
    foreach ($session in @($response.data)) {
        if (-not [string]::IsNullOrWhiteSpace($session.agent_session_id)) { [void]$sessionIds.Add($session.agent_session_id) }
    }
    $paginationToken = $response.pagination_token
} while (-not [string]::IsNullOrWhiteSpace($paginationToken))
$listedCount = $sessionIds.Count

# 2. Session IDs recorded in Application Insights.
if (-not [string]::IsNullOrWhiteSpace($ApplicationInsightsResourceId)) {
    try {
        $subscriptionId = Get-DeploymentSubscriptionId
        $workspaceResourceId = az resource show --ids $ApplicationInsightsResourceId --query properties.WorkspaceResourceId --output tsv
        $workspaceId = az monitor log-analytics workspace show --ids $workspaceResourceId --query customerId --output tsv
        # Single quotes only: double quotes inside the query don't survive the az.cmd wrapper on Windows.
        $query = "AppRequests | where TimeGenerated > ago($($LookbackDays)d) | where Name == 'invoke_agent' | extend p = parse_json(Properties) " +
            "| where tostring(p['gen_ai.agent.name']) == '$AgentName' | summarize by session = tostring(p['azure.ai.agentserver.session_id'])"
        $rows = (az monitor log-analytics query --subscription $subscriptionId --workspace $workspaceId --analytics-query $query --output json 2>$null | Out-String) | ConvertFrom-Json
        foreach ($row in @($rows)) {
            if (-not [string]::IsNullOrWhiteSpace($row.session)) { [void]$sessionIds.Add($row.session) }
        }
    }
    catch {
        Write-Warning "Could not read session IDs from Application Insights ($($_.Exception.Message)); using the sessions API only."
    }
}
Write-Host "Sessions found for '$AgentName': $($sessionIds.Count) ($listedCount from the sessions API). Keeping version $KeepVersion."

# 3. Delete sessions pinned to another version.
$deleted = 0
foreach ($sessionId in $sessionIds) {
    $sessionUrl = "$sessionsUrl/$([Uri]::EscapeDataString($sessionId))?api-version=v1"
    try {
        $session = Invoke-RestMethod -Uri $sessionUrl -Method Get -Headers $headers
    }
    catch {
        if ((Get-StatusCode $_) -eq 404) { continue }
        throw
    }
    $pinnedVersion = [string]$session.version_indicator.agent_version
    if (-not [string]::IsNullOrWhiteSpace($pinnedVersion) -and $pinnedVersion -ne $KeepVersion) {
        Invoke-RestMethod -Uri $sessionUrl -Method Delete -Headers $headers | Out-Null
        Write-Host "Deleted session $($sessionId.Substring(0, [Math]::Min(12, $sessionId.Length)))... ($($session.status), pinned to version $pinnedVersion)."
        $deleted++
    }
}
Write-Host "Deleted $deleted session(s) pinned to older versions of '$AgentName'."
