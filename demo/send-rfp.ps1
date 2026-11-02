#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Emails a synthetic RFP to an RFP Bid Desk instance's mailbox (beat 1: email intake).
.DESCRIPTION
  Sends the RFP text in the email body (the Agent 365 Mail tools can't open attachments) from the signed-in user
  via Microsoft Graph (delegated Mail.Send). The instance searches its own team's answer library, creates a Word
  "compliance matrix and draft" document, shares it with you and replies with a summary and the link.
  The sender must be in ALLOWED_SENDER_DOMAINS (the tenant domain by default).
.EXAMPLE
  pwsh ./demo/send-rfp.ps1 -To bankingbids@diax07991363.onmicrosoft.com
#>
param(
    [Parameter(Mandatory = $true)][string]$To,
    [string]$RfpPath = (Join-Path $PSScriptRoot "rfp/woodgrove-bank-rfp.md"),
    [string]$Subject = "RFP WB-2026-117 - Woodgrove Bank payments analytics hosting (due 2026-11-13)",
    [string]$TenantId,
    [switch]$UseDeviceCode,
    [switch]$SignOut
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot/demo-graph.ps1"

$TenantId = Resolve-DemoTenantId $TenantId $To
Connect-DemoGraph -TenantId $TenantId -UseDeviceCode:$UseDeviceCode -SignOut:$SignOut

$body = (Get-Content $RfpPath -Raw -Encoding utf8) + "`n`nPlease prepare the compliance matrix and a first draft, and tell me what needs SME input."
Send-DemoMail -To $To -Subject $Subject -Body $body
Write-Host "Sent '$Subject' to $To. Expect a reply with the bid document link in 2-5 minutes."
