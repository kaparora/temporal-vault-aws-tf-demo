terraform {
  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.0"
    }
  }
}

provider "vault" {
  address   = var.vault_addr
  token     = var.vault_token
  namespace = var.vault_namespace
}

# ── AWS IAM auth method ───────────────────────────────────────────────────────
resource "vault_auth_backend" "aws" {
  type = "aws"
  path = "aws"
}

resource "vault_aws_auth_backend_role" "worker" {
  backend                  = vault_auth_backend.aws.path
  role                     = "temporal-worker"
  auth_type                = "iam"
  bound_iam_principal_arns = [var.iam_role_arn]
  token_policies           = ["temporal-worker-policy"]
  token_ttl                = 3600
  token_max_ttl            = 14400
}

# ── Database secrets engine ───────────────────────────────────────────────────
resource "vault_mount" "database" {
  path = "database"
  type = "database"
}

resource "vault_database_secret_backend_connection" "postgres" {
  backend = vault_mount.database.path
  name    = "ordersdb"
  allowed_roles = [
    "role-read-orders",
    "role-write-inventory",
    "role-write-payments",
    "role-write-orders",
    "role-write-notifications",
  ]

  postgresql {
    connection_url = "postgresql://{{username}}:{{password}}@${var.db_host}:${var.db_port}/${var.db_name}?sslmode=require"
    username       = var.db_admin_user
    password       = var.db_admin_password
  }
}

# ── Dynamic DB roles (one per activity, least-privilege) ──────────────────────
resource "vault_database_secret_backend_role" "read_orders" {
  backend = vault_mount.database.path
  name    = "role-read-orders"
  db_name = vault_database_secret_backend_connection.postgres.name

  creation_statements = [
    "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';",
    "GRANT SELECT ON orders TO \"{{name}}\";",
  ]
  revocation_statements = ["DROP ROLE IF EXISTS \"{{name}}\";"]

  default_ttl = 3600
  max_ttl     = 14400
}

resource "vault_database_secret_backend_role" "write_inventory" {
  backend = vault_mount.database.path
  name    = "role-write-inventory"
  db_name = vault_database_secret_backend_connection.postgres.name

  creation_statements = [
    "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';",
    "GRANT SELECT, UPDATE ON inventory TO \"{{name}}\";",
  ]
  revocation_statements = ["DROP ROLE IF EXISTS \"{{name}}\";"]

  default_ttl = 3600
  max_ttl     = 14400
}

resource "vault_database_secret_backend_role" "write_payments" {
  backend = vault_mount.database.path
  name    = "role-write-payments"
  db_name = vault_database_secret_backend_connection.postgres.name

  creation_statements = [
    "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';",
    "GRANT INSERT ON payments TO \"{{name}}\";",
  ]
  revocation_statements = ["DROP ROLE IF EXISTS \"{{name}}\";"]

  default_ttl = 3600
  max_ttl     = 14400
}

resource "vault_database_secret_backend_role" "write_orders" {
  backend = vault_mount.database.path
  name    = "role-write-orders"
  db_name = vault_database_secret_backend_connection.postgres.name

  creation_statements = [
    "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';",
    "GRANT UPDATE ON orders TO \"{{name}}\";",
    "GRANT INSERT ON fulfilments TO \"{{name}}\";",
  ]
  revocation_statements = ["DROP ROLE IF EXISTS \"{{name}}\";"]

  default_ttl = 3600
  max_ttl     = 14400
}

resource "vault_database_secret_backend_role" "write_notifications" {
  backend = vault_mount.database.path
  name    = "role-write-notifications"
  db_name = vault_database_secret_backend_connection.postgres.name

  creation_statements = [
    "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';",
    "GRANT INSERT ON notifications TO \"{{name}}\";",
  ]
  revocation_statements = ["DROP ROLE IF EXISTS \"{{name}}\";"]

  default_ttl = 3600
  max_ttl     = 14400
}

# ── Vault policy for the EC2 worker ──────────────────────────────────────────
resource "vault_policy" "worker" {
  name = "temporal-worker-policy"

  policy = <<-EOT
    path "database/creds/role-read-orders"         { capabilities = ["read"] }
    path "database/creds/role-write-inventory"     { capabilities = ["read"] }
    path "database/creds/role-write-payments"      { capabilities = ["read"] }
    path "database/creds/role-write-orders"        { capabilities = ["read"] }
    path "database/creds/role-write-notifications" { capabilities = ["read"] }
    path "auth/token/renew-self"                   { capabilities = ["update"] }
  EOT
}
