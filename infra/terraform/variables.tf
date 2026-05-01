variable "subscription_id" {
  type = string
}

variable "project_name" {
  type    = string
  default = "abenix"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "kubernetes_version" {
  type    = string
  default = "1.29"
}

variable "system_node_size" {
  type    = string
  default = "Standard_D4s_v5"
}

variable "workload_node_size" {
  type    = string
  default = "Standard_D4s_v5"
}

variable "runtime_node_size" {
  type    = string
  default = "Standard_D8s_v5"
}

variable "vnet_address_space" {
  type    = list(string)
  default = ["10.0.0.0/8"]
}

variable "aks_subnet_prefix" {
  type    = string
  default = "10.240.0.0/16"
}

variable "service_cidr" {
  type    = string
  default = "10.1.0.0/16"
}

variable "dns_service_ip" {
  type    = string
  default = "10.1.0.10"
}

variable "domain_name" {
  type    = string
  default = "abenix.io"
}

variable "storage_replication_type" {
  type    = string
  default = "GRS"
}
