output "auth_backend_path" {
  description = "Path of the AWS IAM auth method — referenced by vault_client.py at runtime"
  value       = vault_auth_backend.aws.path
}

output "database_mount_path" {
  description = "Path of the database secrets engine — used when fetching dynamic credentials"
  value       = vault_mount.database.path
}
