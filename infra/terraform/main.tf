resource "azurerm_resource_group" "main" {
  name     = "${var.project_name}-${var.environment}-rg"
  location = var.location
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.project_name}-${var.environment}-logs"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_kubernetes_cluster" "main" {
  name                = "${var.project_name}-${var.environment}-aks"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  dns_prefix          = "${var.project_name}-${var.environment}"
  kubernetes_version  = var.kubernetes_version

  default_node_pool {
    name                = "system"
    vm_size             = var.system_node_size
    min_count           = 2
    max_count           = 5
    enable_auto_scaling = true
    vnet_subnet_id      = azurerm_subnet.aks.id
    os_disk_size_gb     = 128
    os_disk_type        = "Managed"
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin    = "azure"
    load_balancer_sku = "standard"
    service_cidr      = var.service_cidr
    dns_service_ip    = var.dns_service_ip
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }

  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "workload" {
  name                  = "workload"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = var.workload_node_size
  min_count             = 2
  max_count             = 10
  enable_auto_scaling   = true
  vnet_subnet_id        = azurerm_subnet.aks.id
  os_disk_size_gb       = 128

  node_labels = {
    "abenix/pool" = "workload"
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "runtime" {
  name                  = "runtime"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = var.runtime_node_size
  min_count             = 2
  max_count             = 8
  enable_auto_scaling   = true
  vnet_subnet_id        = azurerm_subnet.aks.id
  os_disk_size_gb       = 128

  node_labels = {
    "abenix/pool" = "runtime"
  }

  node_taints = ["abenix/pool=runtime:PreferNoSchedule"]
}
