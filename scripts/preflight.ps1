#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Read-only readiness check before deploying the FinCrime autopilot.
.DESCRIPTION
  Verifies tooling, the Azure CLI identity bound to the target subscription, RBAC,
  hosted-agent region support, model quota and the Microsoft 365 licences that
  autopilots depend on. Makes no changes.
.EXAMPLE
  ./scripts/preflight.ps1 -SubscriptionId <subscription-id> -Location swedencentral
#>
param(
    [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,
    [string]$Location = $(if ($env:AZURE_LOCATION) { $env:AZURE_LOCATION } else { "swedencentral" }),
    [string]$ModelName = $(if ($env:MODEL_NAME_OVERRIDE) { $env:MODEL_NAME_OVERRIDE } else { "gpt-6.1-sol" }),
    [int]$ModelCapacity = $(if ($env:MODEL_CAPACITY) { [int]$env:MODEL_CAPACITY } else { 100 })
)

$ErrorActionPreference = "Continue"
$results = [System.Collections.Generic.List[object]]::new()
function Add-Result([string]$Check, [string]$Status, [string]$Detail) {
    $results.Add([pscustomobject]@{ Check = $Check; Status = $Status; Detail = $Detail })
}

$hostedAgentRegions = @("australiaeast","brazilsouth","canadacentral","canadaeast","eastus","eastus2","francecentral","germanywestcentral","italynorth","japaneast","koreacentral","northcentralus","norwayeast","polandcentral","southafricanorth","southcentralus","southindia","southeastasia","spaincentral","swedencentral","switzerlandnorth","uaenorth","uksouth","westcentralus","westus","westus3")

# Tooling
Add-Result "PowerShell 7+" ($(if ($PSVersionTable.PSVersion.Major -ge 7) { "OK" } else { "FAIL" })) $PSVersionTable.PSVersion.ToString()
$azdVersion = (azd version 2>$null | Select-Object -First 1)
Add-Result "Azure Developer CLI" ($(if ($azdVersion) { "OK" } else { "FAIL" })) "$azdVersion"
$ext = azd ext list --output json 2>$null | ConvertFrom-Json | Where-Object { $_.id -eq "microsoft.foundry" -or $_.Id -eq "microsoft.foundry" }
Add-Result "azd extension microsoft.foundry" ($(if ($ext) { "OK" } else { "FAIL" })) "Install: azd ext install microsoft.foundry"

if (-not $SubscriptionId) {
    Add-Result "Target subscription" "FAIL" "Set AZURE_SUBSCRIPTION_ID or pass -SubscriptionId"
} else {
    $account = az account show --subscription $SubscriptionId --output json 2>$null | ConvertFrom-Json
    if (-not $account) {
        Add-Result "Azure CLI access to subscription" "FAIL" "Run: az login --tenant <tenant-id>"
    } else {
        $isGuest = $account.user.name -match "#EXT#"
        Add-Result "Azure CLI identity for subscription" ($(if ($isGuest) { "FAIL" } else { "OK" })) "$($account.user.name) in tenant $($account.tenantId)"
        $default = az account show --query id --output tsv 2>$null
        Add-Result "az default subscription = target (azd uses az CLI auth)" ($(if ($default -eq $SubscriptionId) { "OK" } else { "WARN" })) "Default is $default. Run: az account set --subscription $SubscriptionId"

        $tok = az account get-access-token --subscription $SubscriptionId --resource-type ms-graph --query accessToken --output tsv 2>$null
        $me = $null
        if ($tok) { try { $me = Invoke-RestMethod -Headers @{ Authorization = "Bearer $tok" } -Uri "https://graph.microsoft.com/v1.0/me?`$select=id,userPrincipalName" } catch { } }
        if ($me) {
            $roles = az role assignment list --subscription $SubscriptionId --assignee-object-id $me.id --include-inherited --query "[].roleDefinitionName" --output tsv 2>$null
            $canProvision = ($roles -contains "Owner") -or (($roles -contains "Contributor") -and (($roles -contains "Role Based Access Control Administrator") -or ($roles -contains "User Access Administrator")))
            Add-Result "Azure RBAC to provision (Owner, or Contributor + RBAC Admin)" ($(if ($canProvision) { "OK" } else { "FAIL" })) (($roles | Sort-Object -Unique) -join ", ")

            try {
                $skus = (Invoke-RestMethod -Headers @{ Authorization = "Bearer $tok" } -Uri "https://graph.microsoft.com/v1.0/subscribedSkus").value
                # Frontier seats come under several SKU names; some tenants get MICROSOFT_AGENT_365_TIER_3, recognisable by its AGENT_365_TOOLS plan.
                $isFrontier = { param($s) $s.skuPartNumber -match "FRONTIER|TEAMMATE|AUTOPILOT|AGENT_365_TIER" -or (@($s.servicePlans.servicePlanName) -match "FRONTIER|TEAMMATE|AUTOPILOT|^AGENT_365_TOOLS$") }
                $qualifying = $skus | Where-Object { $_.skuPartNumber -match "AGENT_365|COPILOT|E7" -and -not (& $isFrontier $_) }
                Add-Result "Qualifying licence (M365 Copilot, Agent 365 or E7)" ($(if ($qualifying) { "OK" } else { "FAIL" })) (($qualifying | ForEach-Object { "$($_.skuPartNumber) $($_.consumedUnits)/$($_.prepaidUnits.enabled)" }) -join "; ")
                $frontier = $skus | Where-Object { & $isFrontier $_ }
                Add-Result "Agent 365 Frontier seats (1 per hired instance)" ($(if ($frontier) { "OK" } else { "ACTION" })) ($(if ($frontier) { ($frontier | ForEach-Object { "$($_.skuPartNumber) $($_.consumedUnits)/$($_.prepaidUnits.enabled)" }) -join "; " } else { "Not found (tenant has: $(($skus | ForEach-Object skuPartNumber) -join ', ')). Global Admin (MCAPS managed tenants: activate Global Administrator in PIM first): M365 admin center > Agents > Overview > Try now > I agree > complete the `$0 checkout, choosing the 'Microsoft 365 Frontier for Autopilots' plan; Billing > Licenses then shows 25 seats." }))
            } catch {
                Add-Result "Microsoft 365 licences" "WARN" "Could not read subscribedSkus (needs a directory role that can read licences)."
            }
        }

        Add-Result "Region supports hosted agents" ($(if ($hostedAgentRegions -contains $Location.ToLower()) { "OK" } else { "FAIL" })) $Location
        $usage = az cognitiveservices usage list --subscription $SubscriptionId --location $Location --output json 2>$null | ConvertFrom-Json
        $quota = $usage | Where-Object { $_.name.value -eq "OpenAI.GlobalStandard.$ModelName" }
        if ($quota) {
            $free = [int]$quota.limit - [int]$quota.currentValue
            Add-Result "Model quota GlobalStandard $ModelName" ($(if ($free -ge $ModelCapacity) { "OK" } else { "FAIL" })) "free $free (need $ModelCapacity)"
        } else {
            Add-Result "Model quota GlobalStandard $ModelName" "FAIL" "No quota entry in $Location"
        }
    }
}

$results | Format-Table -AutoSize -Wrap | Out-String -Width 220 | Write-Host
Write-Host "Human steps after deployment: (1) Global/AI Administrator approves the blueprint in https://admin.cloud.microsoft/?#/agents/all/requested"
Write-Host "                               (2) A licensed user in the hiring scope creates an instance in Teams > Apps > Agents for your team"
if ($results.Status -contains "FAIL") { exit 1 }
