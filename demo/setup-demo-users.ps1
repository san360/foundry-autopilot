#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Creates the demo personas (Elena, Jonas, Lukas) and the "FinCrime Team Leads" hiring group, and can
  licence extra existing users (for example your own account) so they can hire and use the autopilot.
.DESCRIPTION
  Without -Apply the script only prints its plan. With -Apply it:
    * creates three licensed users (password printed once to your console),
    * assigns licences automatically: Microsoft 365 E7 if available (it includes Agent 365 and Copilot),
      otherwise E5 + Agent 365 for the team leads, plus a Teams licence when the base SKU has no Teams,
    * creates the security group "FinCrime Team Leads" (Elena, Lukas) to use as the hiring scope,
    * licences every user in -AlsoLicense with the same set.
  Licences a user already holds are skipped, and so is the Teams add-on when another licence already brings Teams.
  Frontier seats (agent instances only) and device SKUs are never assigned to people. The dry run shows how many
  licences of each kind are needed and free; -Apply stops before any change if some are missing.
  -SkipPersonas licences only the -AlsoLicense users (one-person demo) and creates no personas or group.
  Sign-in: Microsoft Graph PowerShell (interactive) as a Global Administrator or User Administrator of the
  demo tenant. Use -UseAzCli to reuse the Azure CLI identity instead (read-only dry runs work with Global Reader).
  Remove the personas and the group with -Remove.
.EXAMPLE
  pwsh ./demo/setup-demo-users.ps1                                          # dry run, tenant from the azd environment
  pwsh ./demo/setup-demo-users.ps1 -Apply -AlsoLicense you@contoso.onmicrosoft.com
  pwsh ./demo/setup-demo-users.ps1 -Apply -AlsoLicense you@contoso.onmicrosoft.com -SkipPersonas   # one-person demo
#>
param(
    [string]$TenantId,
    [switch]$UseAzCli,
    [string]$SubscriptionId,
    [string]$Domain,
    [string]$UsageLocation,
    [string[]]$LicenseSkus,
    [string]$ManagerLicenseSku = "AGENT_365",
    [string[]]$AlsoLicense = @(),
    [switch]$SkipPersonas,
    [switch]$Apply,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$personas = @(
    @{ alias = "elena.brandt"; name = "Elena Brandt"; title = "Head of FinCrime Ops, Retail & Wealth"; lead = $true },
    @{ alias = "jonas.weber";  name = "Jonas Weber";  title = "L1 AML Analyst, Retail & Wealth";       lead = $false },
    @{ alias = "lukas.meyer";  name = "Lukas Meyer";  title = "Head of FinCrime Ops, Corporate & SME"; lead = $true }
)
$groupName = "FinCrime Team Leads"

if (-not $TenantId) {
    Push-Location (Join-Path $PSScriptRoot "..")
    try { $TenantId = (azd env get-value TENANT_ID 2>$null | Out-String).Trim() } catch { } finally { Pop-Location }
    # azd prints "ERROR: key not found ..." on stdout when the key is missing: accept only a GUID.
    if ($TenantId -notmatch '^[0-9a-fA-F-]{36}$') { $TenantId = $null }
}
if (-not $TenantId -and $UseAzCli -and $SubscriptionId) {
    $TenantId = az account show --subscription $SubscriptionId --query tenantId --output tsv 2>$null
}
if (-not $TenantId) { throw "Pass -TenantId, or run from the repository with an azd environment that has TENANT_ID." }

$script:UseMg = -not $UseAzCli
if ($script:UseMg) {
    if (-not (Get-Module -ListAvailable Microsoft.Graph.Authentication)) {
        Write-Host "Installing Microsoft.Graph.Authentication for the current user..."
        Install-Module Microsoft.Graph.Authentication -Scope CurrentUser -Force
    }
    Import-Module Microsoft.Graph.Authentication
    $scopes = if ($Apply -or $Remove) { @("User.ReadWrite.All", "Group.ReadWrite.All", "Organization.Read.All") } else { @("User.Read.All", "Organization.Read.All") }
    Connect-MgGraph -TenantId $TenantId -Scopes $scopes -NoWelcome
    Write-Host "Signed in to Microsoft Graph as $((Get-MgContext).Account) (tenant $TenantId)"
} else {
    $tokenArgs = if ($SubscriptionId) { @("--subscription", $SubscriptionId) } else { @("--tenant", $TenantId) }
    $token = az account get-access-token @tokenArgs --resource-type ms-graph --query accessToken --output tsv
    if (-not $token) { throw "Could not get a Microsoft Graph token from the Azure CLI. Run: az login --tenant $TenantId" }
    $script:headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }
}

function Graph([string]$Method, [string]$Uri, $Body = $null) {
    $full = "https://graph.microsoft.com/v1.0$Uri"
    if ($script:UseMg) {
        $params = @{ Method = $Method; Uri = $full; OutputType = "PSObject" }
        if ($null -ne $Body) { $params.Body = ($Body | ConvertTo-Json -Depth 6); $params.ContentType = "application/json" }
        return Invoke-MgGraphRequest @params
    }
    $params = @{ Method = $Method; Uri = $full; Headers = $script:headers }
    if ($null -ne $Body) { $params.Body = ($Body | ConvertTo-Json -Depth 6) }
    Invoke-RestMethod @params
}
function Find-User([string]$Upn) {
    try { Graph GET "/users/$([Uri]::EscapeDataString($Upn))?`$select=id,userPrincipalName,usageLocation" } catch { $null }
}
function Free($Sku) { [int]$Sku.prepaidUnits.enabled - [int]$Sku.consumedUnits }

$org = (Graph GET "/organization?`$select=verifiedDomains,countryLetterCode").value | Select-Object -First 1
if (-not $Domain) { $Domain = ($org.verifiedDomains | Where-Object { $_.isDefault } | Select-Object -First 1).name }
if (-not $UsageLocation) { $UsageLocation = if ($org.countryLetterCode) { $org.countryLetterCode } else { "US" } }
Write-Host "Tenant $TenantId, domain $Domain, usage location $UsageLocation"

if ($Remove) {
    foreach ($p in $personas) {
        $u = Find-User "$($p.alias)@$Domain"
        if ($u) { Graph DELETE "/users/$($u.id)" | Out-Null; Write-Host "Deleted $($u.userPrincipalName)" }
    }
    $g = (Graph GET "/groups?`$filter=displayName eq '$groupName'&`$select=id").value | Select-Object -First 1
    if ($g) { Graph DELETE "/groups/$($g.id)" | Out-Null; Write-Host "Deleted group $groupName" }
    return
}

# Licence selection. Frontier seats (for example MICROSOFT_AGENT_365_TIER_3, recognisable by its AGENT_365_TOOLS plan)
# are consumed by autopilot instances at hire, and Common Area Phone / Teams Rooms SKUs belong to devices: never pick
# them for people, even though they include Teams.
function Test-PersonSku($Sku) {
    -not ($Sku.skuPartNumber -match "FRONTIER|TEAMMATE|AUTOPILOT|AGENT_365_TIER|MCOCAP|Teams_Rooms|VIRTUALUSER" -or
        @($Sku.servicePlans.servicePlanName) -contains "AGENT_365_TOOLS")
}
$skus = @((Graph GET "/subscribedSkus").value)
$teamsSkuId = $null
if ($LicenseSkus) {
    $selected = foreach ($part in $LicenseSkus) {
        $sku = $skus | Where-Object { $_.skuPartNumber -eq $part }
        if (-not $sku) { throw "Licence $part not found in the tenant." }
        $sku
    }
} else {
    $people = @($skus | Where-Object { Test-PersonSku $_ })
    # Prefer a base licence with free units; otherwise keep E7/E5 so the plan can say how many to free.
    $base = @($people | Where-Object { $_.skuPartNumber -match "E7" -and (Free $_) -gt 0 }) +
        @($people | Where-Object { $_.skuPartNumber -match "E5" -and (Free $_) -gt 0 }) +
        @($people | Where-Object { $_.skuPartNumber -match "E7|E5" }) | Select-Object -First 1
    if (-not $base) { throw "No Microsoft 365 E7 or E5 licence in the tenant. Pass -LicenseSkus explicitly." }
    $selected = @($base)
    if ($base.servicePlans.servicePlanName -notcontains "TEAMS1") {
        # Select by service plan, not by name: "MICROSOFT_365_E7_NO_TEAMS" contains the word "Teams". Prefer Teams Enterprise.
        $teamsSkus = @($people | Where-Object { $_.skuId -ne $base.skuId -and $_.servicePlans.servicePlanName -contains "TEAMS1" })
        $teams = @($teamsSkus | Where-Object { $_.skuPartNumber -match "Teams_Enterprise|Teams_EEA" }) + $teamsSkus | Select-Object -First 1
        if ($teams) { $selected += $teams; $teamsSkuId = $teams.skuId } else { Write-Warning "No Teams licence in the tenant: the personas won't be able to use Teams." }
    }
}
$selected | ForEach-Object { Write-Host ("Licence {0}: {1} free" -f $_.skuPartNumber, (Free $_)) }
$skuIds = @($selected | ForEach-Object { $_.skuId })

# Team leads manage autopilots: Agent 365 is included in E7; otherwise add the Agent 365 licence if present.
$managerSkuId = $null
$includesAgent365 = $selected | Where-Object { $_.skuPartNumber -match "E7" -or $_.servicePlans.servicePlanName -contains "AGENT_365" }
if (-not $includesAgent365 -and $ManagerLicenseSku) {
    $managerSku = $skus | Where-Object { $_.skuPartNumber -eq $ManagerLicenseSku }
    if ($managerSku) {
        $managerSkuId = $managerSku.skuId
        Write-Host ("Licence {0} (team leads only): {1} free" -f $ManagerLicenseSku, (Free $managerSku))
    } else {
        Write-Host "Licence $ManagerLicenseSku not found; team leads get Microsoft 365 licences only."
    }
}
function Get-SkuName([string]$Id) { ($skus | Where-Object { $_.skuId -eq $Id }).skuPartNumber }
function Get-MissingLicences($User, [string[]]$Ids) {
    # Licences the user doesn't hold yet; the Teams add-on is skipped when another licence already brings Teams.
    if (-not $User) { return @($Ids) }
    $current = @((Graph GET "/users/$($User.id)/licenseDetails").value)
    $held = @($current | ForEach-Object { $_.skuId })
    $hasTeams = @($current | ForEach-Object { $_.servicePlans } | ForEach-Object { $_.servicePlanName }) -contains "TEAMS1"
    @($Ids | Where-Object { ($held -notcontains $_) -and -not ($hasTeams -and $_ -eq $teamsSkuId) })
}

# Plan: who gets which licences, and whether enough are free.
$plan = @()
if (-not $SkipPersonas) {
    foreach ($p in $personas) {
        $upn = "$($p.alias)@$Domain"
        $ids = @($skuIds); if ($p.lead -and $managerSkuId) { $ids += $managerSkuId }
        $existing = Find-User $upn
        $plan += [pscustomobject]@{ Persona = $p; Upn = $upn; User = $existing; Licences = @(Get-MissingLicences $existing $ids) }
    }
}
foreach ($upn in $AlsoLicense) {
    $existing = Find-User $upn
    if (-not $existing) { Write-Warning "User $upn not found; skipped."; continue }
    $ids = @($skuIds); if ($managerSkuId) { $ids += $managerSkuId }
    $plan += [pscustomobject]@{ Persona = $null; Upn = $upn; User = $existing; Licences = @(Get-MissingLicences $existing $ids) }
}

Write-Host "`nPlan:"
foreach ($item in $plan) {
    $what = if ($item.Licences) { ($item.Licences | ForEach-Object { Get-SkuName $_ }) -join " + " } else { "already licensed" }
    if ($item.Persona) {
        $verb = if ($item.User) { "existing user" } else { "create user  " }
        $extra = if ($item.Persona.lead) { "  -> member of '$groupName'" } else { "" }
        Write-Host ("  {0}  {1}  ({2})  [{3}]{4}" -f $verb, $item.Upn, $item.Persona.title, $what, $extra)
    } else {
        Write-Host ("  licence existing user  {0}  [{1}]" -f $item.Upn, $what)
    }
}
$short = @()
foreach ($g in @($plan | ForEach-Object { $_.Licences } | Group-Object)) {
    $sku = $skus | Where-Object { $_.skuId -eq $g.Name }
    Write-Host ("  {0}: needs {1}, {2} free" -f $sku.skuPartNumber, $g.Count, (Free $sku))
    if ($g.Count -gt (Free $sku)) { $short += "$($g.Count - (Free $sku)) x $($sku.skuPartNumber)" }
}
if ($short) { Write-Warning ("Not enough free licences. Unassign from other users first: " + ($short -join ", ")) }
if (-not $Apply) { Write-Host "`nDry run. Re-run with -Apply to make these changes."; return }
if ($short) { throw "Stopped before making any change: not enough free licences." }

function Set-Licences($User, [string[]]$Ids) {
    if (-not $Ids) { return }
    if (-not $User.usageLocation) { Graph PATCH "/users/$($User.id)" @{ usageLocation = $UsageLocation } | Out-Null }
    Graph POST "/users/$($User.id)/assignLicense" @{ addLicenses = @($Ids | ForEach-Object { @{ skuId = $_; disabledPlans = @() } }); removeLicenses = @() } | Out-Null
}

$leadIds = @()
foreach ($item in $plan) {
    $user = $item.User
    $p = $item.Persona
    if ($p -and -not $user) {
        $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 14 | ForEach-Object { [char]$_ }) + "!7a"
        $user = Graph POST "/users" @{
            accountEnabled    = $true
            displayName       = $p.name
            mailNickname      = $p.alias.Replace(".", "")
            userPrincipalName = $item.Upn
            jobTitle          = $p.title
            department        = "Financial Crime Operations"
            usageLocation     = $UsageLocation
            passwordProfile   = @{ forceChangePasswordNextSignIn = $true; password = $password }
        }
        Write-Host "Created $($item.Upn)  initial password: $password"
        $user | Add-Member -NotePropertyName usageLocation -NotePropertyValue $UsageLocation -Force
    } elseif ($p) {
        Write-Host "Exists  $($item.Upn)"
    }
    Set-Licences $user $item.Licences
    if (-not $p) { Write-Host ("Licensed {0} [{1}]" -f $item.Upn, $(if ($item.Licences) { ($item.Licences | ForEach-Object { Get-SkuName $_ }) -join " + " } else { "already licensed" })) }
    if ($p.lead) { $leadIds += $user.id }
}

if ($SkipPersonas) { Write-Host "`nDone. Mailboxes take a few minutes to provision."; return }

$group = (Graph GET "/groups?`$filter=displayName eq '$groupName'&`$select=id").value | Select-Object -First 1
if (-not $group) {
    $group = Graph POST "/groups" @{ displayName = $groupName; mailEnabled = $false; mailNickname = "fincrime-team-leads"; securityEnabled = $true; description = "Hiring scope for the FinCrime Alert Triage autopilot (demo)" }
    Write-Host "Created group $groupName"
}
foreach ($id in $leadIds) {
    try { Graph POST "/groups/$($group.id)/members/`$ref" @{ "@odata.id" = "https://graph.microsoft.com/v1.0/directoryObjects/$id" } | Out-Null } catch { }
}
Write-Host "`nDone. Use '$groupName' as the hiring scope when approving the blueprint. Mailboxes take a few minutes to provision."
