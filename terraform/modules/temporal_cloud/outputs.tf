output "temporal_address" {
  description = "Temporal Cloud mTLS gRPC endpoint for the namespace — written to EC2 worker .env"
  value       = temporalcloud_namespace.main.endpoints.mtls_grpc_address
}

output "temporal_namespace" {
  description = "Temporal Cloud namespace ID (name.account-id) — written to EC2 worker .env"
  value       = temporalcloud_namespace.main.id
}

output "client_cert" {
  description = "PEM client certificate for worker mTLS auth — written to EC2 instance by userdata"
  value       = tls_locally_signed_cert.client.cert_pem
  sensitive   = true
}

output "client_key" {
  description = "PEM client private key for worker mTLS auth — written to EC2 instance by userdata"
  value       = tls_private_key.client.private_key_pem
  sensitive   = true
}
