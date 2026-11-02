param(
    [Parameter(Mandatory = $true)]
    [string]$BlueprintClientId
)

$ErrorActionPreference = "Stop"

. "$PSScriptRoot/common.ps1"

Write-Host "Starting publish script..."
Write-Host "Resources were deployed to: location $env:LOCATION subscriptionId $env:SUBSCRIPTION_ID agentName $env:AGENT_NAME"

$AzureAIProjectEndpoint = $env:AZURE_AI_PROJECT_ENDPOINT
$AgentName = $env:AGENT_NAME
$appVersion = Get-EnvOrDefault "AGENT_APP_VERSION" "1.0.0"
$respondWithoutMention = (Get-EnvOrDefault "CAN_RESPOND_WITHOUT_MENTION" "false") -eq "true"

$agentPublishUrl = "$($AzureAIProjectEndpoint)/agents/$($AgentName)/microsoft365/publish?api-version=2025-11-15-preview"
$scenario = (Get-EnvOrDefault "AUTOPILOT_SCENARIO" "fincrime").ToLowerInvariant()
$azdKeyPrefix = Get-EnvOrDefault "AZD_KEY_PREFIX" ""

# Agent Tools (Microsoft 365 MCP) scopes the administrator consents to. The RFP Bid Desk drops Excel and
# Calendar, which it doesn't use.
$mcpScopes = if ($scenario -eq "rfp") {
    @("McpServers.Word.All", "McpServers.Mail.All", "McpServers.OneDriveSharepoint.All", "McpServers.Teams.All")
} else {
    @("McpServers.Word.All", "McpServers.Mail.All", "McpServers.OneDriveSharepoint.All", "McpServers.Teams.All", "McpServers.Excel.All", "McpServers.Calendar.All")
}
$permissionScopes = @(@{ resourceAppId = "ea9ffc3e-8a23-4a7d-836d-234d7c7565c1"; scopes = $mcpScopes })
# The agent-user Search flow (SEARCH_TOKEN_FLOW=agent_user) needs delegated Azure AI Search access.
if ($scenario -eq "rfp" -and (Get-EnvOrDefault "SEARCH_TOKEN_FLOW" "agent_identity") -eq "agent_user") {
    $permissionScopes += @{ resourceAppId = "880da380-985e-4198-81b9-e05b1cc53158"; scopes = @("user_impersonation") }
}

$texts = if ($scenario -eq "rfp") {
    @{
        display = "RFP Bid Desk"
        short   = "AI coworker that drafts RFP responses from your team's approved past answers."
        full    = "Fabrikam (demo) RFP Bid Desk autopilot. Hire one instance per bid team. It turns RFPs, RFIs and security questionnaires into a compliance matrix and a first draft, reusing approved answers from its own team's answer library in Azure AI Search with citations, flags gaps for SMEs, rewrites sections from Word comments and tracks open items in Teams. Each instance reads only its own team's library, enforced by Azure RBAC on its own identity. Humans own submission, pricing and commitments. Uses synthetic data only."
    }
} else {
    @{
        display = "FinCrime Alert Triage"
        short   = "AI coworker that triages AML, sanctions and KYC alerts for FinCrime Ops."
        full    = "Contoso Bank (demo) FinCrime Alert Triage autopilot. Hire one instance per FinCrime Operations team. It triages transaction-monitoring, sanctions-screening and KYC alerts with read-only tools, writes evidence-based triage memos and case notes for human review, and works in Teams chats and by email under its own identity. It never closes alerts, releases payments or files SARs: humans decide. Uses synthetic data only."
    }
}

# Microsoft365PublishRequest for an autopilot blueprint. Display fields are visible to the
# approver and to people who hire the autopilot: never put secrets in them.
$body = @{
    agentDisplayName            = (Get-EnvOrDefault "AGENT_DISPLAY_NAME" $texts.display)
    publishAsAutopilot          = $true
    publishScope                = "Tenant"
    appVersion                  = $appVersion
    canRespondWithoutMention    = $respondWithoutMention
    shortDescription            = $texts.short
    fullDescription             = $texts.full
    # The publish API rejects developer names longer than 32 characters.
    developerName               = (Get-EnvOrDefault "AGENT_DEVELOPER_NAME" $(if ($scenario -eq "rfp") { "Fabrikam Bid Desk (demo)" } else { "Contoso Bank AI Platform (demo)" }))
    developerWebsiteUrl         = "https://www.microsoft.com"
    privacyUrl                  = "https://privacy.microsoft.com"
    termsOfUseUrl               = "https://www.microsoft.com/legal/terms-of-use"
    # Scopes the tenant administrator consents to in the approval wizard. Without them the
    # autopilot can chat but cannot use the Microsoft 365 tools (Mail, Teams, Word, ...).
    optionalPermissionScopes    = $permissionScopes
}

# The official sample relies on digital_worker_type=m365 (set at agent creation) to provision an
# agent user per instance. The quickstart also documents explicit agentic-user template fields;
# enable them with INCLUDE_AGENTIC_USER_TEMPLATE=true if your tenant requires them.
if ((Get-EnvOrDefault "INCLUDE_AGENTIC_USER_TEMPLATE" "false") -eq "true") {
    $body["useAgenticUserTemplate"] = $true
    $body["agenticUserTemplate"] = @{
        Id                       = "digitalWorkerTemplate"
        File                     = "agenticUserTemplateManifest.json"
        SchemaVersion            = "0.1.0-preview"
        AgentIdentityBlueprintId = $BlueprintClientId
        CommunicationProtocol    = "activityProtocol"
    }
}

$jsonBody = $body | ConvertTo-Json -Depth 10
$aiAzureToken = Get-FoundryAccessToken

Write-Host "Sending Microsoft 365 publish request to $agentPublishUrl..."
Write-Host "JSON Body:"
Write-Host $jsonBody

try {
    $response = Invoke-RestMethod -Uri $agentPublishUrl `
        -Method Post `
        -Headers @{
            "Content-Type"  = "application/json"
            "Accept"        = "application/json"
            "Authorization" = "Bearer $aiAzureToken"
        } `
        -Body $jsonBody

    Write-Host ""
    Write-Host "Response:"
    $response | ConvertTo-Json -Depth 5 | Write-Host
    azd env set "${azdKeyPrefix}PUBLISHED_APP_VERSION" $appVersion | Out-Null
    if ($response.teamsAppId) { azd env set "${azdKeyPrefix}PUBLISHED_TEAMS_APP_ID" $response.teamsAppId | Out-Null }
}
catch {
    $err = $null
    try { $err = $_.ErrorDetails.Message | ConvertFrom-Json } catch { }
    if ($err -and $err.error.code -eq "UserError" -and $err.error.message -like "*version already exists*") {
        Write-Host "Blueprint app version $appVersion is already published. Code changes ship as new agent versions without republishing."
        Write-Host "To change publication metadata, run: azd env set AGENT_APP_VERSION <higher version>; azd provision"
    }
    else {
        throw
    }
}

Write-Host ""
Write-Host "Publish script finished. Next: a Global Administrator or AI Administrator approves the request in"
Write-Host "https://admin.cloud.microsoft/?#/agents/all/requested"
