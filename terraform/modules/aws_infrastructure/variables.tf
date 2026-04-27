# ── Module resource variables ─────────────────────────────────────────────────
# These variables are used directly by Terraform to provision AWS resources
# (VPC, subnets, security groups, IAM, RDS, EC2 launch template).

variable "project_name" {
  description = "Used for naming and tagging all resources"
  type        = string
}

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "ec2_instance_type" {
  type    = string
  default = "t3.micro"
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_name" {
  type    = string
  default = "ordersdb"
}

variable "db_admin_user" {
  type    = string
  default = "postgres"
}

variable "db_admin_password" {
  description = "Initial RDS admin password — rotated by Vault after bootstrap"
  type        = string
  sensitive   = true
}

variable "bootstrap_allowed_cidrs" {
  description = "CIDRs (e.g. your laptop IP) allowed to reach RDS during bootstrap. Empty = no external access."
  type        = list(string)
  default     = []
}

# ── Userdata template variables ───────────────────────────────────────────────
# These variables are passed to userdata.sh via templatefile() and written into
# the EC2 instance at boot — either as .env file entries or as file contents.
# They configure the Temporal worker process that runs as a systemd service.

variable "git_repo_url" {
  description = "Public GitHub repo to clone onto the EC2 worker at boot"
  type        = string
}

variable "git_branch" {
  type    = string
  default = "main"
}

variable "temporal_address" {
  description = "Temporal Cloud gRPC endpoint written to the worker .env"
  type        = string
}

variable "temporal_namespace" {
  description = "Temporal Cloud namespace written to the worker .env"
  type        = string
}

variable "temporal_tls_cert" {
  description = "PEM content of the Temporal Cloud client certificate — written to /opt/temporal-worker/certs/client.pem"
  type        = string
  sensitive   = true
}

variable "temporal_tls_key" {
  description = "PEM content of the Temporal Cloud client key — written to /opt/temporal-worker/certs/client.key"
  type        = string
  sensitive   = true
}

variable "hcp_vault_addr" {
  description = "HCP Vault cluster address written to the worker .env"
  type        = string
}

variable "hcp_vault_namespace" {
  description = "HCP Vault namespace written to the worker .env"
  type        = string
}

variable "vault_role" {
  description = "Vault AWS IAM role name the EC2 worker authenticates as"
  type        = string
  default     = "temporal-worker"
}

variable "task_queue" {
  description = "Temporal task queue the order fulfillment worker listens on"
  type        = string
  default     = "orders-tq"
}
