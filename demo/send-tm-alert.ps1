#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Simulates the transaction-monitoring system: emails an alert notification to an autopilot instance's mailbox.
.DESCRIPTION
  Sends "[TM ALERT] <alert id> <rule name>" from the signed-in user to the autopilot's own mailbox using
  Microsoft Graph (delegated Mail.Send). The autopilot receives it as an Agent 365 email notification,
  triages the alert with its tools and replies by email - with nobody in the loop.
  The sender must be in ALLOWED_SENDER_DOMAINS (the tenant domain by default) or the autopilot ignores it.
  Sign-in is automatic: an existing Microsoft Graph session for the same tenant with Mail.Send is reused
  (no prompt); a session for another tenant is signed out. On Windows, Microsoft Graph PowerShell signs in
  through the Windows account broker (WAM), which reuses accounts and passkeys cached in Windows regardless
  of the browser. If that sign-in fails or you cancel it (for example on a passkey that doesn't work), the
  script falls back to a device code you can complete in any browser. -SignOut forces a different account.
.EXAMPLE
  pwsh ./demo/send-tm-alert.ps1 -To miraretail@diax07991363.onmicrosoft.com -AlertId ALR-2026-1043
.EXAMPLE
  pwsh ./demo/send-tm-alert.ps1 -To miraretail@diax07991363.onmicrosoft.com -SignOut -UseDeviceCode
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$To,
    [string]$AlertId = "ALR-2026-1043",
    # Defaults to TENANT_ID of the active azd environment, then to the tenant of the recipient's domain.
    [string]$TenantId,
    # Go straight to device-code sign-in instead of trying the Windows account broker (WAM) first.
    [switch]$UseDeviceCode,
    # Clear the cached Microsoft Graph PowerShell sign-in before connecting, to pick a different account.
    [switch]$SignOut
)

$ErrorActionPreference = "Stop"

if (-not $TenantId) {
    Push-Location (Join-Path $PSScriptRoot "..")
    try { $TenantId = (azd env get-value TENANT_ID 2>$null | Out-String).Trim() } catch { } finally { Pop-Location }
    # azd prints "ERROR: key not found ..." on stdout when the key is missing: accept only a GUID.
    if ($TenantId -notmatch '^[0-9a-fA-F-]{36}$') { $TenantId = $null }
}
if (-not $TenantId) {
    # No azd environment (e.g. a fresh worktree): resolve the tenant from the recipient's domain.
    $domain = ($To -split "@")[-1]
    try {
        $issuer = (Invoke-RestMethod "https://login.microsoftonline.com/$domain/v2.0/.well-known/openid-configuration").issuer
        if ($issuer -match '([0-9a-fA-F-]{36})') { $TenantId = $Matches[1] }
    } catch { }
}
if (-not $TenantId) { throw "Pass -TenantId, or run from the repository with an azd environment that has TENANT_ID." }
Write-Host "Tenant: $TenantId"

$alertsPath = Join-Path $PSScriptRoot "../src/fincrime_autopilot/data/alerts.json"
$alert = (Get-Content $alertsPath -Raw | ConvertFrom-Json) | Where-Object { $_.alert_id -eq $AlertId }
if (-not $alert) { throw "Unknown alert $AlertId. Valid: ALR-2026-1043 .. ALR-2026-1048" }

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
    if (-not $connected) {
        Connect-MgGraph -TenantId $TenantId -Scopes "Mail.Send" -NoWelcome -UseDeviceCode
    }
}
Write-Host "Sending as $((Get-MgContext).Account)"

# PowerShell 7 parses ISO timestamps into DateTime; keep the ISO form in the mail.
$created = if ($alert.created_at -is [datetime]) { $alert.created_at.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") } else { $alert.created_at }

$content = @"
Transaction Monitoring - new alert (synthetic demo)

Alert ID:     $($alert.alert_id)
Rule:         $($alert.rule_id) - $($alert.rule_name)
Priority:     $($alert.priority)
Segment:      $($alert.segment)
Customer ID:  $($alert.customer_id)
Created:      $created

Please triage this alert and reply with your recommendation.
This is an automated notification from the Transaction Monitoring system.
"@

$message = @{
    message = @{
        subject      = "[TM ALERT] $($alert.alert_id) $($alert.rule_name)"
        body         = @{ contentType = "Text"; content = $content }
        toRecipients = @(@{ emailAddress = @{ address = $To } })
    }
    saveToSentItems = $true
}

Invoke-MgGraphRequest -Method POST -Uri "https://graph.microsoft.com/v1.0/me/sendMail" -Body ($message | ConvertTo-Json -Depth 6)
Write-Host "Sent [TM ALERT] $AlertId to $To. Expect the triage memo as an email reply in 1-3 minutes."
Write-Host "If the mail bounces with 550 5.1.10 the instance mailbox is still provisioning; Teams works first."
