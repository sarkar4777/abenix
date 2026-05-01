resource "azurerm_storage_account" "main" {
  name                     = replace("${var.project_name}${var.environment}sa", "-", "")
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = var.storage_replication_type
  min_tls_version          = "TLS1_2"

  blob_properties {
    versioning_enabled = true
  }
}

resource "azurerm_storage_container" "uploads" {
  name                  = "uploads"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "knowledge_bases" {
  name                  = "knowledge-bases"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}
