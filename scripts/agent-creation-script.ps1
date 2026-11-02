$ErrorActionPreference = "Stop"

. "$PSScriptRoot/common.ps1"

$AzureAIProjectEndpoint = $env:AZURE_AI_PROJECT_ENDPOINT
$AgentName = $env:AGENT_NAME
$AzureContainerRegistryEndpoint = $env:AZURE_CONTAINER_REGISTRY_ENDPOINT

# Runtime settings injected into the hosted agent container.
$authorityEndpoint = "https://login.microsoftonline.com/$($env:TENANT_ID)"
$modelDeployment = $env:MODEL_NAME
$imageTag = Get-EnvOrDefault "AGENT_IMAGE_TAG" "latest"
$scenario = (Get-EnvOrDefault "AUTOPILOT_SCENARIO" "fincrime").ToLowerInvariant()
# Keys this script writes to the azd environment. The RFP Bid Desk wrapper sets a prefix (BID_DESK_)
# so the second agent doesn't overwrite the FinCrime agent's values.
$azdKeyPrefix = Get-EnvOrDefault "AZD_KEY_PREFIX" ""
$scenarioMetadata = @{
    fincrime = @{ tag = "fsi-fincrime-alert-triage"; description = "Contoso Bank FinCrime Alert Triage autopilot (synthetic demo data)." }
    rfp      = @{ tag = "rfp-bid-desk"; description = "Fabrikam RFP Bid Desk autopilot: reuses past bid answers per team (synthetic demo data)." }
}[$scenario]
if (-not $scenarioMetadata) { throw "Unknown AUTOPILOT_SCENARIO '$scenario'. Use fincrime or rfp." }

if (-not $env:TOOLBOX_ENDPOINT) {
    throw "TOOLBOX_ENDPOINT is required. Run setup-toolbox.ps1 before creating the agent version."
}

$runtimeEnvironmentVariables = @{
    "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__AUTHORITY" = $authorityEndpoint
    "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID"  = $env:TENANT_ID
    "ModelDeployment"                                      = $modelDeployment
    "TOOLBOX_ENDPOINT"                                     = $env:TOOLBOX_ENDPOINT
    # Guardrails shared by both scenarios (see src/fincrime_autopilot/guardrails.py)
    "ALLOWED_SENDER_DOMAINS"                               = (Get-EnvOrDefault "ALLOWED_SENDER_DOMAINS" "")
    "MAX_TOOL_ROUNDS"                                      = (Get-EnvOrDefault "MAX_TOOL_ROUNDS" "8")
    # Message content capture in Application Insights is off by default for a
    # financial-services posture. Set CAPTURE_MESSAGE_CONTENT=true to show prompts in traces.
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"   = (Get-EnvOrDefault "CAPTURE_MESSAGE_CONTENT" "false")
    # Same image, two autopilots: fincrime (default) or rfp (RFP Bid Desk). Not AGENT_*: Foundry reserves the
    # AGENT_* and FOUNDRY_* prefixes for container environment variables and rejects the version.
    "AUTOPILOT_SCENARIO"                                       = $scenario
}

# TOKEN_DEBUG / TOKEN_FOOTER: token inspector (/whoami, claim summaries in logs); never logs raw tokens.
$optionalSettings = @("TRIAGE_NOTIFY_CHAT_NAME", "SEGMENT_SCOPE_RULES", "TOKEN_DEBUG", "TOKEN_FOOTER", "MCP_ENFORCE_ALLOWLIST")
if ($scenario -eq "rfp") {
    # BID_COLLEAGUES / COLLEAGUE_*: agent-to-agent collaboration between hired instances (docs/17).
    $optionalSettings += @("SEARCH_ENDPOINT", "SEARCH_TOKEN_FLOW", "BID_TEAMS", "BID_TEAM_RULES", "BID_TEAM_CHAT_NAME",
        "BID_COLLEAGUES", "COLLEAGUE_MAX_TURNS", "COLLEAGUE_WINDOW_SECONDS")
}
foreach ($optional in $optionalSettings) {
    $value = [Environment]::GetEnvironmentVariable($optional)
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        $runtimeEnvironmentVariables[$optional] = $value
    }
}

$agentEndpoint = @{
    protocols = @("activity")
    protocol_configuration = @{
        activity = @{
            enable_m365_public_endpoint = $true
        }
    }
}

$agentUrl = "$($AzureAIProjectEndpoint)/agents/$($AgentName)/versions?api-version=2025-11-15-preview"

$agentCreationBody = @{
    definition = @{
        kind = "hosted"
        image = "$($AzureContainerRegistryEndpoint)/fincrime-autopilot:$imageTag"
        cpu = (Get-EnvOrDefault "AGENT_CPU" "1")
        memory = (Get-EnvOrDefault "AGENT_MEMORY" "2Gi")
        environment_variables = $runtimeEnvironmentVariables
        container_protocol_versions = @(
            @{
                protocol = "activity_protocol"
                version = "2.0.0"
            }
        )
    }
    metadata = @{
        enableVnextExperience = "true"
        scenario = $scenarioMetadata.tag
        dataClassification = "synthetic-demo"
    }
    description = $scenarioMetadata.description
    agent_endpoint = $agentEndpoint
    digital_worker_type = "m365"
}

$jsonBody = $agentCreationBody | ConvertTo-Json -Depth 6

Write-Host "Getting access token for https://ai.azure.com ..."
$aiAzureToken = Get-FoundryAccessToken

$headers = @{
    "Content-Type" = "application/json"
    "Accept" = "application/json"
    "Authorization" = "Bearer $aiAzureToken"
    "Foundry-Features" = "DigitalWorker=V1Preview"
}

Write-Host "Creating agent version at: $agentUrl"
Write-Host "JSON Body:"
Write-Host $jsonBody

$response = Invoke-RestMethod -Uri $agentUrl `
    -Method Post `
    -Headers $headers `
    -Body $jsonBody `
    -ErrorAction Stop

Write-Host ""
Write-Host "Response:"
$response | ConvertTo-Json -Depth 100 | Write-Host

$agentVersion = $response.version
$agentGuid = $response.agent_guid
$agentDefaultInstanceClientId = $response.instance_identity.client_id
$blueprintClientId = $response.blueprint.client_id
Write-Host "Agent GUID: $agentGuid"
Write-Host "Agent Version: $agentVersion"
Write-Host "Blueprint Client Id: $blueprintClientId"

$maxRetries = 30
$delaySeconds = 10
$provisioningStatus = $response.status
if (-not $provisioningStatus) { $provisioningStatus = "Unknown" }

Write-Host "Initial provisioning status: $provisioningStatus"

$pollUrl = "$($AzureAIProjectEndpoint)/agents/$($AgentName)/versions/$($agentVersion)?api-version=2025-11-15-preview"

if ($provisioningStatus -ne "active" -and $provisioningStatus -ne "failed") {
    for ($i = 1; $i -lt $maxRetries; $i++) {
        Write-Host "Waiting ${delaySeconds}s before poll $($i + 1)/${maxRetries}..."
        Start-Sleep -Seconds $delaySeconds

        try {
            $pollResponse = Invoke-RestMethod -Uri $pollUrl `
                -Method Get `
                -Headers $headers `
                -ErrorAction Stop

            $provisioningStatus = $pollResponse.status
            if (-not $provisioningStatus) { $provisioningStatus = "Unknown" }

            # Identity client IDs may not be populated until provisioning completes.
            if ($pollResponse.instance_identity.client_id) {
                $agentDefaultInstanceClientId = $pollResponse.instance_identity.client_id
            }
            if ($pollResponse.blueprint.client_id) {
                $blueprintClientId = $pollResponse.blueprint.client_id
            }
        }
        catch {
            Write-Host "Poll failed: $($_.Exception.Message)"
        }

        Write-Host "Provisioning status: $provisioningStatus"

        if ($provisioningStatus -eq "active" -or $provisioningStatus -eq "failed") {
            break
        }
    }
}

Write-Host "Agent version provisioned: $provisioningStatus"

if ($provisioningStatus -ne "active") {
    throw "Agent version provisioning status is '$provisioningStatus', expected 'active'."
}

$accountScope = "/subscriptions/$($env:SUBSCRIPTION_ID)/resourceGroups/$($env:RESOURCE_GROUP)/providers/Microsoft.CognitiveServices/accounts/$($env:ACCOUNT_NAME)"
$projectScope = "$accountScope/projects/$($env:PROJECT_NAME)"
$foundryUserRoleName = "Foundry User"

Write-Host "Granting Foundry User role to client id $agentDefaultInstanceClientId on scope $projectScope"

$roleAssignmentOutput = az role assignment create `
    --assignee $agentDefaultInstanceClientId `
    --role $foundryUserRoleName `
    --scope $projectScope 2>&1 | Out-String

if ($LASTEXITCODE -eq 0) {
    Write-Host "Foundry User role assignment created."
}
elseif ($roleAssignmentOutput -match "RoleAssignmentExists") {
    Write-Host "Foundry User role assignment already exists, skipping."
}
else {
    throw "Failed to create Foundry User role assignment: $roleAssignmentOutput"
}

# Endpoint authorization. The sample default (BotServiceRbac) needs a caller object ID
# that email and Word-comment events may not carry, so email-triggered alerts would be
# rejected. Entra + BotServiceTenant accepts callers from this tenant; the agent code then
# filters senders by domain (ALLOWED_SENDER_DOMAINS) and drops cross-tenant activities.
$schemeNames = (Get-EnvOrDefault "AGENT_AUTH_SCHEMES" "Entra,BotServiceTenant").Split(",") |
    ForEach-Object { $_.Trim() } | Where-Object { $_ }
$agentEndpoint["authorization_schemes"] = @($schemeNames | ForEach-Object { @{ "type" = $_ } })

$patchUrl = "$($AzureAIProjectEndpoint)/agents/$($AgentName)?api-version=2025-11-15-preview"
$patchBody = @{
    agent_endpoint = $agentEndpoint
} | ConvertTo-Json -Depth 6

Write-Host "Patching agent endpoint at: $patchUrl"
Write-Host "Patch Body:"
Write-Host $patchBody

$patchResponse = Invoke-RestMethod -Uri $patchUrl `
    -Method Patch `
    -Headers $headers `
    -Body $patchBody `
    -ErrorAction Stop

Write-Host ""
Write-Host "Patch Response:"
$patchResponse | ConvertTo-Json -Depth 100 | Write-Host

azd env set "${azdKeyPrefix}AGENT_VERSION" "$agentVersion" | Out-Null
azd env set "${azdKeyPrefix}AGENT_BLUEPRINT_CLIENT_ID" "$blueprintClientId" | Out-Null
azd env set "${azdKeyPrefix}AGENT_INSTANCE_CLIENT_ID" "$agentDefaultInstanceClientId" | Out-Null

return [pscustomobject]@{
    AgentGuid = $agentGuid
    BlueprintClientId = $blueprintClientId
}
