#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Creates (or updates) the RFP Bid Desk hosted agent: a second autopilot next to FinCrime, same container image.
.DESCRIPTION
  Runs agent-creation-script.ps1, stop-agent-sessions.ps1 and publish-digital-worker.ps1 with AUTOPILOT_SCENARIO=rfp
  and the bid desk's own agent name, so it gets its own blueprint, approval request and hires (for example
  BankingBids and PublicSectorBids). Values written to the azd environment are prefixed with BID_DESK_ so the
  FinCrime agent's values are kept. The post-provision hook runs it when ENABLE_BID_DESK=true; you can also run it
  on its own after the image is built.
  Settings (azd env set ...): BID_DESK_SEARCH_TOKEN_FLOW (agent_identity | agent_user, default agent_identity),
  BID_DESK_TOKEN_DEBUG (default true), BID_DESK_TOKEN_FOOTER (default false), BID_TEAM_CHAT_NAME, BID_TEAMS,
  BID_TEAM_RULES, BID_COLLEAGUES (written by sync-bid-desk-instances.ps1), COLLEAGUE_MAX_TURNS,
  COLLEAGUE_WINDOW_SECONDS, BID_DESK_DISPLAY_NAME, BID_DESK_APP_VERSION.
.EXAMPLE
  pwsh ./scripts/deploy-bid-desk-agent.ps1
#>
param(
    [switch]$SkipPublish
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot/common.ps1"

$agentName = Get-EnvOrDefault "BID_DESK_AGENT_NAME" ""
if (-not $agentName) { throw "BID_DESK_AGENT_NAME is empty. Set ENABLE_BID_DESK=true and run azd provision first." }
if (-not $env:SEARCH_ENDPOINT) { throw "SEARCH_ENDPOINT is empty. Set ENABLE_BID_DESK=true and run azd provision first." }

$variables = @{
    AGENT_NAME         = $agentName
    AUTOPILOT_SCENARIO     = "rfp"
    AZD_KEY_PREFIX     = "BID_DESK_"
    SEARCH_TOKEN_FLOW  = (Get-EnvOrDefault "BID_DESK_SEARCH_TOKEN_FLOW" "agent_identity")
    TOKEN_DEBUG        = (Get-EnvOrDefault "BID_DESK_TOKEN_DEBUG" "true")
    TOKEN_FOOTER       = (Get-EnvOrDefault "BID_DESK_TOKEN_FOOTER" "false")
    AGENT_DISPLAY_NAME = (Get-EnvOrDefault "BID_DESK_DISPLAY_NAME" "RFP Bid Desk")
    AGENT_APP_VERSION  = (Get-EnvOrDefault "BID_DESK_APP_VERSION" "1.0.0")
    # FinCrime-only settings must not leak into the bid desk.
    SEGMENT_SCOPE_RULES     = ""
    TRIAGE_NOTIFY_CHAT_NAME = ""
}

Invoke-WithEnvironment -Variables $variables -Action {
    Write-Host "===============Creating RFP Bid Desk agent version ($agentName)==============="
    $agentInfo = & "$PSScriptRoot/agent-creation-script.ps1"
    Write-Host "Bid desk agent GUID: $($agentInfo.AgentGuid), blueprint client id: $($agentInfo.BlueprintClientId)"

    Write-Host "===============Retiring bid desk sessions pinned to older versions==============="
    & "$PSScriptRoot/stop-agent-sessions.ps1" -AgentName $agentName

    if (-not $SkipPublish) {
        Write-Host "===============Publishing the RFP Bid Desk digital worker==============="
        & "$PSScriptRoot/publish-digital-worker.ps1" -BlueprintClientId $agentInfo.BlueprintClientId
    }
}

Write-Host ""
Write-Host "Next: approve 'RFP Bid Desk' in the Microsoft 365 admin center, hire BankingBids and PublicSectorBids, then run"
Write-Host "  pwsh ./scripts/grant-bid-team-access.ps1 -Instance BankingBids -Team banking -Apply"
Write-Host "  pwsh ./scripts/grant-bid-team-access.ps1 -Instance PublicSectorBids -Team publicsector -Apply"
