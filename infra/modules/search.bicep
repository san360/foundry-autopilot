// Azure AI Search for the RFP Bid Desk: one index per bid team (created by scripts/setup-search-indexes.ps1).
// Entra ID only (API keys disabled). The deployer gets control-plane and index-write roles to create and load
// the indexes. Nobody gets data-plane access at service scope: each hired instance's own identity is granted
// Search Index Data Reader on its team's index only (scripts/grant-bid-team-access.ps1, index-scope RBAC,
// which Bicep can't express because indexes are not ARM resources). The Foundry project and the hosted
// container's default identity get no Search role at all.

param searchServiceName string
param location string = resourceGroup().location
param tags object = {}

@allowed(['basic', 'standard'])
param sku string = 'basic'

@description('Object ID of the deploying identity. Gets Search Service Contributor and Search Index Data Contributor to create and load the indexes.')
param principalId string = ''

@allowed(['User', 'ServicePrincipal', 'Group'])
param principalType string = 'User'

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    disableLocalAuth: true
    semanticSearch: 'free'
  }
}

var searchServiceContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var searchIndexDataContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')

resource deployerServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(search.id, principalId, searchServiceContributor)
  scope: search
  properties: {
    roleDefinitionId: searchServiceContributor
    principalId: principalId
    principalType: principalType
  }
}

resource deployerIndexDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(search.id, principalId, searchIndexDataContributor)
  scope: search
  properties: {
    roleDefinitionId: searchIndexDataContributor
    principalId: principalId
    principalType: principalType
  }
}

output name string = search.name
output endpoint string = 'https://${search.name}.search.windows.net'
output id string = search.id
