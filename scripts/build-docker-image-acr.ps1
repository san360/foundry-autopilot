# Build the agent image with Azure Container Registry Tasks (cloud build, no local Docker needed).

. "$PSScriptRoot/common.ps1"

Set-Location "$($PSScriptRoot)/../src/fincrime_autopilot"

Remove-Item "./__pycache__" -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Filter "__pycache__" -Recurse -Force -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "./.vs" -Recurse -Force -ErrorAction SilentlyContinue

$acrLoginServer = $env:AZURE_CONTAINER_REGISTRY_ENDPOINT
$registryName = $acrLoginServer.Split(".")[0]
$subscriptionId = Get-DeploymentSubscriptionId

# A unique tag per build keeps every agent version pinned to its own image,
# which makes rollback (re-pinning an older version) reliable.
$imageTag = Get-Date -Format "yyyyMMdd-HHmmss"
$imageName = "fincrime-autopilot:$imageTag"

Write-Host "Building image $imageName using ACR Build in registry: $registryName"

# Queue the cloud build and poll its status instead of streaming logs: on Windows the Azure CLI's
# log streaming can crash on non-ASCII build output (cp1252 UnicodeEncodeError) while the build
# itself succeeds.
$env:PYTHONIOENCODING = "utf-8"
$queueOutput = az acr build `
    --subscription $subscriptionId `
    --registry $registryName `
    --image $imageName `
    --image "fincrime-autopilot:latest" `
    --file "./foundry-infra/Dockerfile" `
    --no-wait `
    . 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "Queuing the ACR build failed with exit code ${LASTEXITCODE}: $queueOutput"
}
# The run ID is reported on stderr ("Queued a build with ID: dt3"); fall back to the newest run.
$match = [regex]::Match($queueOutput, "Queued a build with ID:\s*(\S+)")
$runId = if ($match.Success) { $match.Groups[1].Value } else {
    az acr task list-runs --subscription $subscriptionId --registry $registryName --top 1 --query "[0].runId" --output tsv
}
if (-not $runId) { throw "Could not determine the ACR run ID. Output: $queueOutput" }
Write-Host "Queued ACR run $runId; waiting for completion..."

$status = "Queued"
$deadline = (Get-Date).AddMinutes(20)
while ($status -in @("Queued", "Started", "Running") -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 10
    $status = az acr task show-run --subscription $subscriptionId --registry $registryName --run-id $runId --query status --output tsv
    Write-Host "  ACR run $runId status: $status"
}

if ($status -ne "Succeeded") {
    $logFile = Join-Path ([IO.Path]::GetTempPath()) "acr-$runId.log"
    az acr task logs --subscription $subscriptionId --registry $registryName --run-id $runId --no-format 2>&1 | Out-File -Encoding utf8 $logFile
    throw "ACR build run $runId finished with status '$status'. Logs: $logFile"
}

$env:AGENT_IMAGE_TAG = $imageTag
azd env set AGENT_IMAGE_TAG $imageTag | Out-Null

Write-Host "Image built and pushed successfully: $acrLoginServer/$imageName"
