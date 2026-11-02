#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Sample: registers a custom MCP API in Entra with app roles and assigns them to RFP Bid Desk instances.
.DESCRIPTION
  Companion to docs/15-mcp-behind-ai-gateway.md. NOT called by azd or any hook.
  1. Creates (or updates) the app registration of the MCP API: v2 access tokens, Application ID URI
     api://<client-id> (+ -ExtraIdentifierUri, for example the API Management URL), delegated scope
     Mcp.Bids.Access and the app roles Mcp.Bids.Read, Mcp.Bids.Banking, Mcp.Bids.PublicSector
     (allowed member types Application and User).
  2. Creates its service principal and, unless -AllowUnassigned, sets appRoleAssignmentRequired so Entra
     refuses tokens to clients without an assignment.
  3. Per instance: assigns the team role to that instance's agent identity (app-only token -> roles claim).
  4. Fleet-wide (unless -SkipFleetRole): assigns Mcp.Bids.Read to the blueprint principal and adds the MCP API
     to the blueprint's inheritablePermissions (roles only), so every current and future instance inherits it.
     Inherited roles are not visible in Graph: check the roles claim with /whoami.
  Without -Apply it only prints the plan.
  Needs: Cloud Application Administrator or Application Administrator (app registration and app role
  assignments) and Agent ID Administrator, or Agent ID Developer as blueprint owner (inheritable permissions).
.EXAMPLE
  pwsh ./samples/mcp-behind-ai-gateway/register-and-assign-mcp-roles.ps1
  pwsh ./samples/mcp-behind-ai-gateway/register-and-assign-mcp-roles.ps1 -ExtraIdentifierUri https://apim-zava.azure-api.net/bids-mcp -Apply
  pwsh ./samples/mcp-behind-ai-gateway/register-and-assign-mcp-roles.ps1 -Assignments @{ BankingBids = 'Mcp.Bids.Banking' } -SkipFleetRole -Apply
#>
param(
    [string]$BlueprintAppId,
    [string]$ApiDisplayName = "Zava Bids MCP",
    [string[]]$ExtraIdentifierUri = @(),
    [hashtable]$Assignments = @{ BankingBids = "Mcp.Bids.Banking"; PublicSectorBids = "Mcp.Bids.PublicSector" },
    [string]$FleetRole = "Mcp.Bids.Read",
    [switch]$SkipFleetRole,
    [switch]$AllowUnassigned,
    [string]$SubscriptionId,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$roleDefinitions = [ordered]@{
    "Mcp.Bids.Read"         = "May call the bids MCP server through the gateway"
    "Mcp.Bids.Banking"      = "May read banking bid answers"
    "Mcp.Bids.PublicSector" = "May read public sector bid answers"
}
$scopeValue = "Mcp.Bids.Access"

function Get-AzdValue([string]$Key) {
    Push-Location (Join-Path $PSScriptRoot "../..")
    try { $v = (azd env get-value $Key 2>$null | Out-String).Trim() } catch { $v = $null } finally { Pop-Location }
    if ($v -and $v -notmatch '^ERROR') { return $v }
    return $null
}
if (-not $BlueprintAppId) { $BlueprintAppId = Get-AzdValue "BID_DESK_AGENT_BLUEPRINT_CLIENT_ID" }
if (-not $SubscriptionId) { $SubscriptionId = Get-AzdValue "AZURE_SUBSCRIPTION_ID" }
if (-not $BlueprintAppId) { throw "Pass -BlueprintAppId or run from the repository with a provisioned azd environment (ENABLE_BID_DESK=true)." }
foreach ($role in @($Assignments.Values) + @($FleetRole)) {
    if (-not $roleDefinitions.Contains($role)) { throw "Unknown role '$role'. Known: $($roleDefinitions.Keys -join ', ')" }
}

$tokenArgs = @("account", "get-access-token", "--resource-type", "ms-graph", "--query", "accessToken", "--output", "tsv")
if ($SubscriptionId) { $tokenArgs += @("--subscription", $SubscriptionId) }
$token = az @tokenArgs
if ($LASTEXITCODE -ne 0 -or -not $token) { throw "No Microsoft Graph token from the Azure CLI. Run az login." }
$graphHeaders = @{ Authorization = "Bearer $token"; "OData-Version" = "4.0" }
function Graph([string]$Method, [string]$Path, $Body = $null, [string]$Version = "v1.0") {
    $params = @{ Method = $Method; Uri = "https://graph.microsoft.com/$Version$Path"; Headers = $graphHeaders }
    if ($null -ne $Body) { $params.Body = ($Body | ConvertTo-Json -Depth 8); $params.ContentType = "application/json" }
    Invoke-RestMethod @params
}
function Escape([string]$Value) { return $Value.Replace("'", "''") }

# --- Current state ---------------------------------------------------------------------------------
$app = @((Graph GET "/applications?`$filter=displayName eq '$(Escape $ApiDisplayName)'&`$select=id,appId,identifierUris,appRoles,api").value) | Select-Object -First 1
$sp = $null
if ($app) { $sp = @((Graph GET "/servicePrincipals?`$filter=appId eq '$($app.appId)'&`$select=id,appId,appRoles,appRoleAssignmentRequired").value) | Select-Object -First 1 }

$identities = @((Graph GET "/servicePrincipals/microsoft.graph.agentIdentity?`$filter=agentIdentityBlueprintId eq '$BlueprintAppId'&`$select=id,appId,displayName" -Version beta).value)
$targets = foreach ($name in $Assignments.Keys) {
    $identity = $identities | Where-Object { $_.displayName -eq $name } | Select-Object -First 1
    if (-not $identity) { $identity = $identities | Where-Object { $_.displayName -like "*$name*" } | Select-Object -First 1 }
    if (-not $identity) { throw "No agent identity named '$name' for blueprint $BlueprintAppId. Hired instances: $(($identities | ForEach-Object displayName) -join ', ')" }
    [pscustomobject]@{ Name = $name; Id = $identity.id; Role = $Assignments[$name] }
}
$blueprintSp = @((Graph GET "/servicePrincipals?`$filter=appId eq '$BlueprintAppId'&`$select=id,displayName").value) | Select-Object -First 1
$blueprintApp = @((Graph GET "/applications?`$filter=appId eq '$BlueprintAppId'&`$select=id,displayName").value) | Select-Object -First 1
if (-not $SkipFleetRole -and (-not $blueprintSp -or -not $blueprintApp)) { throw "Blueprint $BlueprintAppId (application and principal) not found in this tenant." }

# --- Plan ----------------------------------------------------------------------------------------
Write-Host "Plan for MCP API '$ApiDisplayName':"
if ($app) { Write-Host "  App registration exists: client ID $($app.appId)" } else { Write-Host "  Create the app registration (v2 tokens, scope $scopeValue, roles $($roleDefinitions.Keys -join ', '))" }
$missingRoles = @($roleDefinitions.Keys | Where-Object { -not $app -or @($app.appRoles.value) -notcontains $_ })
if ($app -and $missingRoles) { Write-Host "  Add app roles: $($missingRoles -join ', ')" }
Write-Host "  Identifier URIs: api://<client-id> $($ExtraIdentifierUri -join ' ')"
Write-Host "  Service principal: $(if ($sp) { 'exists' } else { 'create' }); appRoleAssignmentRequired = $(-not $AllowUnassigned)"
foreach ($t in $targets) { Write-Host "  Assign '$($t.Role)' to agent identity $($t.Name) ($($t.Id))" }
if (-not $SkipFleetRole) {
    Write-Host "  Assign '$FleetRole' to blueprint principal $($blueprintSp.displayName) ($($blueprintSp.id))"
    Write-Host "  Make the MCP API inheritable on the blueprint (roles: allAllowed, scopes: none)"
}
if (-not $Apply) { Write-Host "`nPlan only. Re-run with -Apply to make these changes."; return }

# --- Apply: app registration ---------------------------------------------------------------------
function New-RoleObject([string]$Value) {
    @{ id = [guid]::NewGuid().ToString(); value = $Value; displayName = $Value; description = $roleDefinitions[$Value]
       allowedMemberTypes = @("Application", "User"); isEnabled = $true }
}
if (-not $app) {
    $app = Graph POST "/applications" @{
        displayName    = $ApiDisplayName
        signInAudience = "AzureADMyOrg"
        api            = @{
            requestedAccessTokenVersion = 2
            oauth2PermissionScopes      = @(@{
                id = [guid]::NewGuid().ToString(); value = $scopeValue; type = "Admin"; isEnabled = $true
                adminConsentDisplayName = "Access the bids MCP server"; adminConsentDescription = "Lets the agent call the bids MCP server tools."
            })
        }
        appRoles       = @($roleDefinitions.Keys | ForEach-Object { New-RoleObject $_ })
    }
    Write-Host "Created app registration $($app.appId)."
} else {
    if ($app.api.requestedAccessTokenVersion -ne 2) { Graph PATCH "/applications/$($app.id)" @{ api = @{ requestedAccessTokenVersion = 2 } } | Out-Null }
    if ($missingRoles) {
        $roles = @($app.appRoles) + @($missingRoles | ForEach-Object { New-RoleObject $_ })
        Graph PATCH "/applications/$($app.id)" @{ appRoles = $roles } | Out-Null
        Write-Host "Added app roles: $($missingRoles -join ', ')."
    }
}
# v2 tokens must be set before an HTTPS Application ID URI can be added.
$uris = @(@("api://$($app.appId)") + $ExtraIdentifierUri + @($app.identifierUris) | Where-Object { $_ } | Select-Object -Unique)
Graph PATCH "/applications/$($app.id)" @{ identifierUris = $uris } | Out-Null
Write-Host "Identifier URIs: $($uris -join ', ')"

# --- Apply: service principal --------------------------------------------------------------------
if (-not $sp) {
    $sp = Graph POST "/servicePrincipals" @{ appId = $app.appId }
    Write-Host "Created service principal $($sp.id)."
}
Graph PATCH "/servicePrincipals/$($sp.id)" @{ appRoleAssignmentRequired = (-not $AllowUnassigned) } | Out-Null
for ($i = 0; $i -lt 10; $i++) {
    $sp = Graph GET "/servicePrincipals/$($sp.id)?`$select=id,appRoles"
    if (@($sp.appRoles.value) -contains $FleetRole) { break }
    Start-Sleep -Seconds 3
}
function Get-RoleId([string]$Value) {
    $id = ($sp.appRoles | Where-Object value -eq $Value | Select-Object -First 1).id
    if (-not $id) { throw "App role $Value not found on the service principal yet; re-run in a minute." }
    return $id
}
$existing = @((Graph GET "/servicePrincipals/$($sp.id)/appRoleAssignedTo?`$top=999").value)
function Grant-Role([string]$PrincipalId, [string]$Label, [string]$Role) {
    $roleId = Get-RoleId $Role
    if ($existing | Where-Object { $_.principalId -eq $PrincipalId -and $_.appRoleId -eq $roleId }) { Write-Host "'$Role' already assigned to $Label."; return }
    Graph POST "/servicePrincipals/$($sp.id)/appRoleAssignedTo" @{ principalId = $PrincipalId; resourceId = $sp.id; appRoleId = $roleId } | Out-Null
    Write-Host "Assigned '$Role' to $Label."
}

# --- Apply: per-instance and fleet roles ---------------------------------------------------------
foreach ($t in $targets) { Grant-Role $t.Id "agent identity $($t.Name)" $t.Role }
if (-not $SkipFleetRole) {
    Grant-Role $blueprintSp.id "blueprint principal $($blueprintSp.displayName)" $FleetRole
    $base = "/applications/microsoft.graph.agentIdentityBlueprint/$($blueprintApp.id)/inheritablePermissions"
    $entry = @{ inheritableScopes = @{ "@odata.type" = "#microsoft.graph.noScopes"; kind = "none" }
                inheritableRoles  = @{ "@odata.type" = "#microsoft.graph.allAllowedRoles"; kind = "allAllowed" } }
    $current = @((Graph GET $base).value) | Where-Object { $_.resourceAppId -eq $app.appId }
    if ($current) { Graph PATCH "$base/$($app.appId)" @{ inheritableRoles = $entry.inheritableRoles } | Out-Null }
    else { Graph POST $base (@{ resourceAppId = $app.appId } + $entry) | Out-Null }
    Write-Host "The MCP API is inheritable (roles) on the blueprint. Also declare '$FleetRole' in the blueprint's requiredResourceAccess if inheritance doesn't show in tokens (doc 15 section 7)."
}

Write-Host "`nDone. MCP API client ID: $($app.appId). Token resource for the container: api://$($app.appId)"
Write-Host "Check with '/whoami' once the container requests a token for it (doc 15 section 4.5)."
