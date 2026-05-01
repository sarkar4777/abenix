output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "aks_cluster_fqdn" {
  value = azurerm_kubernetes_cluster.main.fqdn
}

output "kube_config" {
  value     = azurerm_kubernetes_cluster.main.kube_config_raw
  sensitive = true
}

output "storage_account_name" {
  value = azurerm_storage_account.main.name
}

output "ingress_ip" {
  value = azurerm_public_ip.ingress.ip_address
}

output "dns_nameservers" {
  value = azurerm_dns_zone.main.name_servers
}

output "key_vault_uri" {
  value = azurerm_key_vault.main.vault_uri
}
