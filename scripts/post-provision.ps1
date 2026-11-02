#!/usr/bin/env pwsh

if ($env:SKIP_POSTPROVISION -eq "true") {
    Write-Host "Skipping post-provision data-plane operations because SKIP_POSTPROVISION=true."
    return
}

Write-Host "Starting post-provision script..."

Write-Host "Resources were deployed to: location $env:LOCATION subscriptionId $env:SUBSCRIPTION_ID agentName $env:AGENT_NAME"

. "$PSScriptRoot/common.ps1"
Write-Host "===============Checking Foundry data-plane access==============="
Wait-FoundryDataPlaneAccess

Write-Host "===============Creating Foundry Toolbox==============="
& "$PSScriptRoot/setup-toolbox.ps1"

# Write-Host "===============Building and pushing Docker image==============="
& "$PSScriptRoot/build-docker-image-acr.ps1"

Write-Host "===============Creating Agent Version==============="
$agentInfo = & "$PSScriptRoot/agent-creation-script.ps1"
$agentGuid = $agentInfo.AgentGuid
$blueprintClientId = $agentInfo.BlueprintClientId
Write-Host "Agent GUID: $agentGuid, Blueprint Client Id: $blueprintClientId"

# Sessions stay pinned to the version they started on: retire them once the new version is active.
Write-Host "===============Retiring Sessions Pinned to Older Versions==============="
& "$PSScriptRoot/stop-agent-sessions.ps1"

Write-Host "===============Publishing digital worker==============="

& "$PSScriptRoot/publish-digital-worker.ps1" -BlueprintClientId $blueprintClientId

# RFP Bid Desk: a second autopilot (same image, AUTOPILOT_SCENARIO=rfp) with per-team Azure AI Search indexes.
if ($env:ENABLE_BID_DESK -eq "true") {
    Write-Host "===============Creating the bid teams' answer libraries (Azure AI Search)==============="
    & "$PSScriptRoot/setup-search-indexes.ps1"
    & "$PSScriptRoot/deploy-bid-desk-agent.ps1"
}

Write-Host ""
Write-Host "Post-provision script finished."
