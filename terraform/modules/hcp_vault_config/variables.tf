# ── Module resource variables ─────────────────────────────────────────────────
# Used by Terraform to configure Vault content: auth methods, secrets engines,
# dynamic DB roles, and policies. These tell Terraform which Vault cluster to
# configure and what AWS identity is allowed to authenticate.

variable "vault_addr" {
  description = "HCP Vault cluster public endpoint URL"
  type        = string
}

variable "vault_namespace" {
  description = "HCP Vault namespace (typically 'admin' for HCP clusters)"
  type        = string
  default     = "admin"
}

variable "vault_token" {
  description = "Admin token used to configure Vault — from hcp_vault_cluster or provided directly"
  type        = string
  sensitive   = true
}

variable "aws_region" {
  description = "AWS region — used to scope the Vault AWS auth backend"
  type        = string
  default = "us-east-1"
}

variable "iam_role_arn" {
  description = "ARN of the EC2 IAM role — Vault AWS auth is bound to this identity"
  type        = string
}

variable "project_name" {
  description = "Used for naming Vault resources"
  type        = string
}

# ── Database configuration variables ─────────────────────────────────────────
# Passed to the Vault database secrets engine so it can connect to RDS,
# create dynamic users, and revoke them at lease expiry.

variable "db_host" {
  description = "RDS PostgreSQL hostname (from aws_infrastructure module output)"
  type        = string
}

variable "db_port" {
  type    = number
  default = 5432
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "ordersdb"
}

variable "db_admin_user" {
  description = "vault_admin PostgreSQL user — used by Vault to create/revoke dynamic users"
  type        = string
  default     = "vault_admin"
}

variable "db_admin_password" {
  description = "vault_admin password — Vault rotates this after bootstrap so it is no longer known"
  type        = string
  sensitive   = true
}
