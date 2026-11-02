#!/usr/bin/env pwsh
# Shared Microsoft Graph sign-in for the demo senders (same behaviour as send-tm-alert.ps1): reuse a session for
# the same tenant with Mail.Send, sign out a session for another tenant, try the Windows account broker first and
# fall back to a device code.

function Resolve-DemoTenantId([string]$TenantId, [string]$Recipient) {
    if (-not $TenantId) {
        Push-Location (Join-Path $PSScriptRoot "..")
        try { $TenantId = (azd env get-value TENANT_ID 2>$null | Out-String).Trim() } catch { } finally { Pop-Location }
        if ($TenantId -notmatch '^[0-9a-fA-F-]{36}$') { $TenantId = $null }
    }
    if (-not $TenantId -and $Recipient) {
        $domain = ($Recipient -split "@")[-1]
        try {
            $issuer = (Invoke-RestMethod "https://login.microsoftonline.com/$domain/v2.0/.well-known/openid-configuration").issuer
            if ($issuer -match '([0-9a-fA-F-]{36})') { $TenantId = $Matches[1] }
        } catch { }
    }
    if (-not $TenantId) { throw "Pass -TenantId, or run from the repository with an azd environment that has TENANT_ID." }
    return $TenantId
}

function Connect-DemoGraph([string]$TenantId, [switch]$UseDeviceCode, [switch]$SignOut) {
    if (-not (Get-Module -ListAvailable Microsoft.Graph.Authentication)) {
        Write-Host "Installing Microsoft.Graph.Authentication for the current user..."
        Install-Module Microsoft.Graph.Authentication -Scope CurrentUser -Force
    }
    Import-Module Microsoft.Graph.Authentication
    $ctx = Get-MgContext
    if ($ctx -and ($SignOut -or $ctx.TenantId -ne $TenantId -or $ctx.Scopes -notcontains "Mail.Send")) {
        if (-not $SignOut) {
            Write-Host "Signing out $($ctx.Account): wrong tenant or missing Mail.Send."
            Disconnect-MgGraph | Out-Null
        }
        $ctx = $null
    }
    if ($SignOut) {
        try { Disconnect-MgGraph -ErrorAction Stop | Out-Null } catch { }
        Remove-Item (Join-Path $HOME ".mg") -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not $ctx) {
        $connected = $false
        if (-not $UseDeviceCode) {
            try {
                Connect-MgGraph -TenantId $TenantId -Scopes "Mail.Send" -NoWelcome -ErrorAction Stop
                $connected = $true
            } catch {
                Write-Warning "Windows sign-in failed or was cancelled ($($_.Exception.Message)). Falling back to device code."
            }
        }
        if (-not $connected) { Connect-MgGraph -TenantId $TenantId -Scopes "Mail.Send" -NoWelcome -UseDeviceCode }
    }
    Write-Host "Sending as $((Get-MgContext).Account)"
}

function Send-DemoMail([string[]]$To, [string]$Subject, [string]$Body) {
    $message = @{
        message = @{
            subject      = $Subject
            body         = @{ contentType = "Text"; content = $Body }
            toRecipients = @($To | ForEach-Object { @{ emailAddress = @{ address = $_ } } })
        }
        saveToSentItems = $true
    }
    Invoke-MgGraphRequest -Method POST -Uri "https://graph.microsoft.com/v1.0/me/sendMail" -Body ($message | ConvertTo-Json -Depth 6)
}
