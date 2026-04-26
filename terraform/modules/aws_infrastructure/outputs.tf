output "ec2_public_ip" {
  description = "Public IP of the EC2 worker instance"
  value       = aws_instance.worker.public_ip
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)"
  value       = aws_db_instance.postgres.endpoint
}

output "rds_host" {
  description = "RDS PostgreSQL hostname only"
  value       = aws_db_instance.postgres.address
}

output "iam_role_arn" {
  description = "ARN of the EC2 IAM role — used to bind Vault AWS auth"
  value       = aws_iam_role.worker.arn
}

