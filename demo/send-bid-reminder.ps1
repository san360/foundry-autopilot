#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Triggers the RFP Bid Desk's daily deadline check (beat 3: proactive reminder in the bid team's Teams chat).
.DESCRIPTION
  Hosted agents only run when an activity arrives, so a scheduler sends a "[bid-desk:daily-check]" email to each
  instance. The instance reads its bid documents, and for bids due within -WithinDays days (default 7) posts the open
  items and owners to the Teams chat named BID_TEAM_CHAT_NAME. It doesn't reply to the email, and posts nothing when
  no bid is due within the window (the demo bid WB-2026-117 is due 2026-11-13: use -WithinDays 14).
  This script is the on-demand trigger for demos. For a real schedule without another Azure service, use a
  Power Automate scheduled cloud flow (Recurrence, daily 08:00 -> Office 365 Outlook "Send an email (V2)" to the
  instance mailbox with the same subject) from an account in ALLOWED_SENDER_DOMAINS. See docs/12.
.EXAMPLE
  pwsh ./demo/send-bid-reminder.ps1 -To bankingbids@diax07991363.onmicrosoft.com -WithinDays 14
#>
param(
    [Parameter(Mandatory = $true)][string[]]$To,
    [ValidateRange(1, 365)][int]$WithinDays = 7,
    [string]$TenantId,
    [switch]$UseDeviceCode,
    [switch]$SignOut
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot/demo-graph.ps1"

$TenantId = Resolve-DemoTenantId $TenantId $To[0]
Connect-DemoGraph -TenantId $TenantId -UseDeviceCode:$UseDeviceCode -SignOut:$SignOut

$subject = "[bid-desk:daily-check] $(Get-Date -Format 'yyyy-MM-dd')"
$body = "[bid-desk:daily-check] Scheduled daily deadline check from the bid desk scheduler. Post reminders for bids due within $WithinDays days to the bid team chat."
foreach ($recipient in $To) {
    Send-DemoMail -To @($recipient) -Subject $subject -Body $body
    Write-Host "Sent '$subject' to $recipient."
}
Write-Host "Reminders appear in the bid team's Teams chat in 1-3 minutes (only for bids due within $WithinDays days)."
