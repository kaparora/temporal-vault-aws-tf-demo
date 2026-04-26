# ── Module resource variables ─────────────────────────────────────────────────
# Used by Terraform to provision the HCP Vault cluster and its HVN
# (HashiCorp Virtual Network — required container for every HCP Vault cluster).

variable "project_name" {
  description = "Used for naming HCP resources"
  type        = string
}

variable "hcp_client_id" {
  description = "HCP service principal client ID"
  type        = string
}

variable "hcp_client_secret" {
  description = "HCP service principal client secret"
  type        = string
  sensitive   = true
}

variable "hcp_project_id" {
  description = "HCP project ID where the Vault cluster will be created"
  type        = string
}

variable "cluster_id" {
  description = "Unique identifier for the HCP Vault cluster"
  type        = string
  default     = "temporal-vault"
}

variable "cluster_tier" {
  description = "HCP Vault cluster tier — dev is free and sufficient for a demo"
  type        = string
  default     = "dev"
}

variable "hvn_region" {
  description = "AWS region for the HCP HashiCorp Virtual Network"
  type        = string
  default     = "us-east-1"
}

variable "hvn_cidr" {
  description = "CIDR block for the HCP Virtual Network (must not overlap with your AWS VPC)"
  type        = string
  default     = "172.25.16.0/20"
}
