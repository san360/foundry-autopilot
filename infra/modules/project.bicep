// Parameters for the project module
param accountName string
param projectName string

param containerRegistryName string
param location string = resourceGroup().location
param tags object = {}

param cognitiveServicesSku string = 'S0'

// Container Registry SKU
@allowed(['Basic', 'Standard', 'Premium'])
param containerRegistrySku string = 'Basic'

param modelName string
param modelVersion string

@description('Model deployment capacity (thousands of tokens per minute)')
param modelCapacity int = 100

@description('Name of the Log Analytics workspace')
param logAnalyticsName string

@description('Name of the Application Insights component')
param applicationInsightsName string

@description('Object ID of the deploying user or service principal (azd provides AZURE_PRINCIPAL_ID). It gets Foundry User on the project so the post-provision hook can create the Toolbox and agent versions, and so the smoke test and evaluation can call the model.')
param principalId string = ''

@allowed(['User', 'ServicePrincipal', 'Group'])
param principalType string = 'User'

resource account 'Microsoft.CognitiveServices/accounts@2025-09-01' existing = {
  name: accountName
}

// Cognitive Services Project (child resource)
resource project 'Microsoft.CognitiveServices/accounts/projects@2026-03-01' = {
  parent: account
  name: projectName
  location: location
  kind: 'AIServices'
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: cognitiveServicesSku
  }
  properties: {
    displayName: projectName
  }
}

// Azure Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: containerRegistryName
  location: location
  tags: tags
  sku: {
    name: containerRegistrySku
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

// Built-in AcrPull role definition ID
var acrPullRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

// Role assignment: Grant AcrPull role to the project's system managed identity
resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, project.id, acrPullRoleDefinitionId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: acrPullRoleDefinitionId
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

var cognitiveServicesUserRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')

// Foundry User (formerly Azure AI User): data-plane access to the project for the deploying identity.
// Owner/Contributor alone grant no data actions, so a fresh subscription would otherwise fail with 403.
var foundryUserRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')

resource deployerFoundryUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(project.id, principalId, foundryUserRoleDefinitionId)
  scope: project
  properties: {
    roleDefinitionId: foundryUserRoleDefinitionId
    principalId: principalId
    principalType: principalType
  }
}

// Role assignment: Grant AcrPull role to the project's system managed identity
resource cogServicesUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, project.id, cognitiveServicesUserRoleDefinitionId)
  scope: account
  properties: {
    roleDefinitionId: cognitiveServicesUserRoleDefinitionId
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}


// The project and the model deployment are both child operations on the same Foundry
// account; running them in parallel can fail with "RequestConflict: Another operation is
// in progress". Serialize them.
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  name: modelName
  parent: account
  dependsOn: [
    project
  ]
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

module monitoring 'monitoring.bicep' = {
  name: 'monitoring-deployment'
  params: {
    logAnalyticsName: logAnalyticsName
    applicationInsightsName: applicationInsightsName
    location: location
    tags: tags
    projectPrincipalId: project.identity.principalId
    deployerPrincipalId: principalId
    deployerPrincipalType: principalType
  }
}

resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-09-01' = {
  parent: project
  name: applicationInsightsName
  properties: {
    category: 'AppInsights'
    target: monitoring.outputs.id
    #disable-next-line BCP036
    authType: 'ProjectManagedIdentity'
    isSharedToAll: false
    metadata: {
      ApiType: 'Azure'
      ResourceId: monitoring.outputs.id
      ApplicationInsightsConnectionString: monitoring.outputs.connectionString
    }
  }
}

output acrloginServer string = containerRegistry.properties.loginServer

output foundryProjectEndpoint string = project.properties.endpoints['AI Foundry API']

output foundryProjectPrincipalId string = project.identity.principalId

output applicationInsightsConnectionString string = monitoring.outputs.connectionString

output applicationInsightsResourceId string = monitoring.outputs.id
