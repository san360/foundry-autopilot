#!/usr/bin/env pwsh
# Shared helpers for the deployment scripts.

function Get-DeploymentSubscriptionId {
    $subscriptionId = $env:SUBSCRIPTION_ID
    if (-not $subscriptionId) { $subscriptionId = $env:AZURE_SUBSCRIPTION_ID }
    if (-not $subscriptionId) { throw "SUBSCRIPTION_ID or AZURE_SUBSCRIPTION_ID is required." }
    return $subscriptionId
}

function Get-FoundryAccessToken {
    # Bind the token to the deployment subscription (not just the tenant): when the
    # same person has a guest identity in the tenant, '--tenant' can silently pick
    # the guest account, which has no Foundry permissions.
    $subscriptionId = Get-DeploymentSubscriptionId
    $token = az account get-access-token `
        --subscription $subscriptionId `
        --resource https://ai.azure.com `
        --query accessToken `
        --output tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
        throw "Failed to acquire an access token for https://ai.azure.com in subscription $subscriptionId."
    }
    return $token
}

function Get-EnvOrDefault {
    param([string]$Name, [string]$Default)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

function Invoke-WithEnvironment {
    # Runs a script block with temporary environment variable values and restores the previous
    # values afterwards (used to deploy the second autopilot with the same scripts).
    param([hashtable]$Variables, [scriptblock]$Action)
    $previous = @{}
    foreach ($name in $Variables.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name)
        [Environment]::SetEnvironmentVariable($name, [string]$Variables[$name])
    }
    try { return & $Action }
    finally {
        foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name]) }
    }
}

function Wait-FoundryDataPlaneAccess {
    # Role assignments made during provisioning (Foundry User for the deploying identity) can take a few
    # minutes to propagate. Wait for them before the hook calls the Foundry data plane.
    param(
        [string]$ProjectEndpoint = $env:AZURE_AI_PROJECT_ENDPOINT,
        [int]$TimeoutMinutes = 10
    )
    $uri = "$($ProjectEndpoint.TrimEnd('/'))/agents?api-version=2025-11-15-preview"
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ($true) {
        $token = Get-FoundryAccessToken
        try {
            Invoke-RestMethod -Uri $uri -Headers @{ Authorization = "Bearer $token" } -Method Get -ErrorAction Stop | Out-Null
            Write-Host "Foundry data-plane access confirmed."
            return
        }
        catch {
            $status = $null
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
            if ($status -notin @(401, 403)) {
                Write-Warning "Foundry data-plane check returned HTTP $status ($($_.Exception.Message)); continuing."
                return
            }
            if ((Get-Date) -gt $deadline) {
                throw "No Foundry data-plane access after $TimeoutMinutes minutes (HTTP $status). The deploying identity needs the 'Foundry User' role on the project."
            }
            Write-Host "Waiting for the 'Foundry User' role assignment to propagate (HTTP $status)..."
            Start-Sleep -Seconds 20
        }
    }
}
