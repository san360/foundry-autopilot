#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Creates the bid teams' answer-library indexes in Azure AI Search and loads the synthetic past-bid answers.
.DESCRIPTION
  One index per bid team (default bids-banking and bids-publicsector), same schema (demo/rfp/library/index-schema.json),
  documents from demo/rfp/library/<team>.json. Runs as the deploying identity with Entra ID (API keys are disabled
  on the service); main.bicep gives that identity Search Service Contributor and Search Index Data Contributor.
  The libraries are not baked into the container image and the container gets no Search role: only each hired
  instance's own identity can read its team's index (scripts/grant-bid-team-access.ps1). Re-runnable.
.EXAMPLE
  pwsh ./scripts/setup-search-indexes.ps1
#>
param(
    [string]$SearchEndpoint = $env:SEARCH_ENDPOINT,
    [string]$LibraryPath = (Join-Path $PSScriptRoot "../demo/rfp/library"),
    [int]$TimeoutMinutes = 10
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot/common.ps1"

if ([string]::IsNullOrWhiteSpace($SearchEndpoint)) { throw "SEARCH_ENDPOINT is empty. Set ENABLE_BID_DESK=true and run azd provision." }
$SearchEndpoint = $SearchEndpoint.TrimEnd("/")
$apiVersion = "2024-07-01"

$teams = [ordered]@{ banking = "bids-banking"; publicsector = "bids-publicsector" }
if ($env:BID_TEAMS) {
    $teams = [ordered]@{}
    ($env:BID_TEAMS | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $teams[$_.Name.ToLowerInvariant()] = $_.Value.index }
}

$schemaTemplate = Get-Content (Join-Path $LibraryPath "index-schema.json") -Raw | ConvertFrom-Json
$schemaTemplate.PSObject.Properties.Remove("_comment")

function Get-SearchToken {
    $token = az account get-access-token --subscription (Get-DeploymentSubscriptionId) --resource https://search.azure.com --query accessToken --output tsv
    if ($LASTEXITCODE -ne 0 -or -not $token) { throw "No Azure AI Search token from the Azure CLI. Run az login." }
    return $token
}

function Invoke-Search([string]$Method, [string]$Path, $Body) {
    # New role assignments take a few minutes to reach the Search data plane: retry 401/403 until the deadline.
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ($true) {
        $headers = @{ Authorization = "Bearer $(Get-SearchToken)"; "Content-Type" = "application/json" }
        try {
            $params = @{ Method = $Method; Uri = "$SearchEndpoint$Path"; Headers = $headers }
            if ($Body -is [string]) { $params.Body = [Text.Encoding]::UTF8.GetBytes($Body) }
            elseif ($null -ne $Body) { $params.Body = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 20)) }
            return Invoke-RestMethod @params
        }
        catch {
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            if ($status -notin @(401, 403) -or (Get-Date) -gt $deadline) {
                throw "Search $Method $Path failed (HTTP $status): $($_.ErrorDetails.Message)"
            }
            Write-Host "  Waiting for the Search role assignments to propagate (HTTP $status)..."
            Start-Sleep -Seconds 20
        }
    }
}

foreach ($team in $teams.Keys) {
    $index = $teams[$team]
    $docsPath = Join-Path $LibraryPath "$team.json"
    if (-not (Test-Path $docsPath)) { Write-Warning "No library file $docsPath for team '$team'; skipping."; continue }

    $schema = $schemaTemplate | ConvertTo-Json -Depth 20 | ConvertFrom-Json
    $schema | Add-Member -NotePropertyName name -NotePropertyValue $index -Force
    Invoke-Search PUT "/indexes/$index`?api-version=$apiVersion" $schema | Out-Null
    Write-Host "Index $index is ready."

    # Send the documents as written (ConvertFrom-Json would turn the ISO dates into DateTime values).
    $raw = Get-Content $docsPath -Raw -Encoding utf8
    $docCount = @($raw | ConvertFrom-Json).Count
    $batch = '{"value": ' + ($raw -replace '\{\s*"id"\s*:', '{"@search.action": "mergeOrUpload", "id":') + '}'
    $result = Invoke-Search POST "/indexes/$index/docs/index?api-version=$apiVersion" $batch
    $failed = @($result.value | Where-Object { -not $_.status })
    if ($failed.Count) { throw "$($failed.Count) document(s) failed to load into $index." }
    Write-Host "Loaded $docCount synthetic past answers into $index (team '$team')."
}

Write-Host "Answer libraries ready. Grant each hired instance access to its own index with scripts/grant-bid-team-access.ps1."
