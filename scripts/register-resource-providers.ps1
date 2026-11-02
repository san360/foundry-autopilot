$ErrorActionPreference = "Stop"

. "$PSScriptRoot/common.ps1"
$subscriptionId = Get-DeploymentSubscriptionId

# Everything the Bicep template and the hosted-agent runtime need. A fresh subscription (for example a
# new MCAPS tenant) usually has none of these registered yet.
$requiredProviders = @(
    "Microsoft.CognitiveServices",
    "Microsoft.ContainerRegistry",
    "Microsoft.OperationalInsights",
    "Microsoft.Insights",
    "Microsoft.App",
    "Microsoft.ContainerService"
)
# RFP Bid Desk: Azure AI Search for the bid teams' answer libraries.
if ((Get-EnvOrDefault "ENABLE_BID_DESK" "false") -eq "true") { $requiredProviders += "Microsoft.Search" }

function Get-RegistrationState([string]$Namespace) {
    $state = az provider show --subscription $subscriptionId --namespace $Namespace --query registrationState --output tsv
    if ($LASTEXITCODE -ne 0) { throw "Failed to query registration state for resource provider '$Namespace'." }
    return $state
}

# Start every missing registration first, then wait for all of them (registrations run in parallel).
$pending = @()
foreach ($provider in $requiredProviders) {
    if ((Get-RegistrationState $provider) -eq "Registered") {
        Write-Host "Resource provider '$provider' is already registered."
        continue
    }
    Write-Host "Registering resource provider '$provider'..."
    az provider register --subscription $subscriptionId --namespace $provider --output none
    if ($LASTEXITCODE -ne 0) { throw "Failed to register resource provider '$provider'." }
    $pending += $provider
}

$deadline = (Get-Date).AddMinutes(15)
while ($pending.Count -gt 0) {
    if ((Get-Date) -gt $deadline) { throw "Timed out waiting for resource providers: $($pending -join ', ')" }
    Start-Sleep -Seconds 15
    $pending = @($pending | Where-Object { (Get-RegistrationState $_) -ne "Registered" })
    if ($pending.Count -gt 0) { Write-Host "  still registering: $($pending -join ', ')" }
}
Write-Host "All required resource providers are registered."
