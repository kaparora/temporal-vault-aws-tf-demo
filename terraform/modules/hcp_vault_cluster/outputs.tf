output "vault_public_endpoint" {
  description = "Public HTTPS endpoint of the HCP Vault cluster"
  value       = hcp_vault_cluster.main.vault_public_endpoint_url
}

output "vault_namespace" {
  description = "HCP Vault namespace — always 'admin' for HCP clusters"
  value       = "admin"
}

output "admin_token" {
  description = "Short-lived admin token for configuring Vault content — consumed by hcp_vault_config module"
  value       = hcp_vault_cluster_admin_token.main.token
  sensitive   = true
}
