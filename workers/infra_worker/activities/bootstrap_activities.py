import json
import os
from dataclasses import dataclass

import asyncpg
import hvac
from temporalio import activity

from workers.common.secrets import read_secret
from workers.infra_worker.terraform_runner import run_terraform

# ── Output dataclasses ────────────────────────────────────────────────────────
# Returned by each Terraform activity and passed as inputs to downstream ones.

@dataclass
class TemporalCloudOutput:
    temporal_address: str
    temporal_namespace: str
    client_cert: str
    client_key: str


@dataclass
class HCPVaultClusterOutput:
    vault_public_endpoint: str
    vault_namespace: str
    admin_token: str


@dataclass
class AWSInfraOutput:
    ec2_public_ip: str
    rds_host: str
    rds_endpoint: str
    iam_role_arn: str


# ── Input dataclasses ─────────────────────────────────────────────────────────
# Only values derived from previous activities — sensitive creds come from env vars.

@dataclass
class AWSInfraInput:
    # From Temporal Cloud activity
    temporal_address: str
    temporal_namespace: str
    temporal_tls_cert: str
    temporal_tls_key: str
    # From HCP Vault cluster activity
    hcp_vault_addr: str
    hcp_vault_namespace: str


@dataclass
class HCPVaultConfigInput:
    # From HCP Vault cluster activity
    vault_public_endpoint: str
    vault_namespace: str
    admin_token: str
    # From AWS infra activity
    iam_role_arn: str
    rds_host: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _terraform_dir() -> str:
    return os.getenv("TERRAFORM_DIR", "./terraform")


def _module_path(module_name: str) -> str:
    return f"{_terraform_dir()}/modules/{module_name}"


# ── Terraform activities ──────────────────────────────────────────────────────

@activity.defn
async def run_temporal_cloud_module() -> TemporalCloudOutput:
    """
    Provisions the Temporal Cloud namespace and generates mTLS certificates.
    Sensitive: TEMPORAL_CLOUD_API_KEY read from env or file — never passed as workflow input.
    """
    outputs = run_terraform(
        _module_path("temporal_cloud"),
        variables={
            "temporal_cloud_api_key": read_secret("TEMPORAL_CLOUD_API_KEY", is_file=True),
            "namespace_name":         os.getenv("TEMPORAL_NAMESPACE", "temporal-vault-demo"),
            "namespace_region":       os.getenv("TEMPORAL_NAMESPACE_REGION", "aws-us-east-1"),
        },
    )
    return TemporalCloudOutput(
        temporal_address=outputs["temporal_address"],
        temporal_namespace=outputs["temporal_namespace"],
        client_cert=outputs["client_cert"],
        client_key=outputs["client_key"],
    )


@activity.defn
async def run_hcp_vault_cluster_module() -> HCPVaultClusterOutput:
    """
    Provisions the HCP Vault cluster and HVN.
    Sensitive: HCP_CLIENT_ID, HCP_CLIENT_SECRET, HCP_PROJECT_ID read from env.
    """
    outputs = run_terraform(
        _module_path("hcp_vault_cluster"),
        variables={
            "hcp_client_id":     os.environ["HCP_CLIENT_ID"],
            "hcp_client_secret": os.environ["HCP_CLIENT_SECRET"],
            "hcp_project_id":    os.environ["HCP_PROJECT_ID"],
            "project_name":      os.getenv("PROJECT_NAME", "temporal-vault-aws-demo"),
            "cluster_id":        os.getenv("HCP_VAULT_CLUSTER_ID", "temporal-vault"),
            "cluster_tier":      os.getenv("HCP_VAULT_CLUSTER_TIER", "dev"),
            "hvn_region":        os.getenv("AWS_REGION", "us-east-1"),
        },
    )
    return HCPVaultClusterOutput(
        vault_public_endpoint=outputs["vault_public_endpoint"],
        vault_namespace=outputs["vault_namespace"],
        admin_token=outputs["admin_token"],
    )


@activity.defn
async def run_aws_infrastructure_module(inp: AWSInfraInput) -> AWSInfraOutput:
    """
    Provisions VPC, EC2, RDS, and IAM resources.
    EC2 userdata receives Temporal and Vault config so the worker starts on boot.
    Sensitive: AWS credentials and DB admin password read from env.
    """
    bootstrap_cidrs = os.getenv("BOOTSTRAP_ALLOWED_CIDRS", "")
    cidrs_json = json.dumps(bootstrap_cidrs.split(",")) if bootstrap_cidrs else json.dumps([])

    outputs = run_terraform(
        _module_path("aws_infrastructure"),
        variables={
            "project_name":            os.getenv("PROJECT_NAME", "temporal-vault-aws-demo"),
            "aws_region":              os.getenv("AWS_REGION", "us-east-1"),
            "db_admin_password":       os.environ["DB_ADMIN_PASSWORD"],
            "git_repo_url":            os.environ["GIT_REPO_URL"],
            "git_branch":              os.getenv("GIT_BRANCH", "main"),
            "bootstrap_allowed_cidrs": cidrs_json,
            # From Temporal Cloud activity
            "temporal_address":        inp.temporal_address,
            "temporal_namespace":      inp.temporal_namespace,
            "temporal_tls_cert":       inp.temporal_tls_cert,
            "temporal_tls_key":        inp.temporal_tls_key,
            # From HCP Vault cluster activity
            "hcp_vault_addr":          inp.hcp_vault_addr,
            "hcp_vault_namespace":     inp.hcp_vault_namespace,
        },
    )
    return AWSInfraOutput(
        ec2_public_ip=outputs["ec2_public_ip"],
        rds_host=outputs["rds_host"],
        rds_endpoint=outputs["rds_endpoint"],
        iam_role_arn=outputs["iam_role_arn"],
    )


@activity.defn
async def run_hcp_vault_config_module(inp: HCPVaultConfigInput) -> None:
    """
    Configures HCP Vault: AWS IAM auth, database secrets engine, dynamic DB roles,
    and the temporal-worker-policy. No outputs — purely configuration.
    Sensitive: DB admin password read from env.
    """
    run_terraform(
        _module_path("hcp_vault_config"),
        variables={
            "vault_addr":         inp.vault_public_endpoint,
            "vault_namespace":    inp.vault_namespace,
            "vault_token":        inp.admin_token,
            "aws_region":         os.getenv("AWS_REGION", "us-east-1"),
            "iam_role_arn":       inp.iam_role_arn,
            "project_name":       os.getenv("PROJECT_NAME", "temporal-vault-aws-demo"),
            "db_host":            inp.rds_host,
            "db_name":            os.getenv("DB_NAME", "ordersdb"),
            "db_admin_user":      os.getenv("DB_ADMIN_USER", "vault_admin"),
            "db_admin_password":  os.environ["DB_ADMIN_PASSWORD"],
        },
    )


@activity.defn
async def create_db_schema() -> None:
    """
    Creates database schema: orders, inventory, payments, fulfilments, notifications tables.
    Connects as vault_admin using credentials from env vars.
    Idempotent: uses CREATE TABLE IF NOT EXISTS.
    """
    conn = await asyncpg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_ADMIN_USER", "vault_admin"),
        password=os.environ["DB_ADMIN_PASSWORD"],
        database=os.getenv("DB_NAME", "ordersdb"),
        ssl="require",
    )

    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                product_id TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id),
                amount DECIMAL(10, 2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS fulfilments (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id),
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id),
                notification_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    finally:
        await conn.close()


@activity.defn
async def seed_db() -> None:
    """
    Seeds database with sample data: 3 orders and 5 inventory items.
    Connects as vault_admin using credentials from env vars.
    Idempotent: uses INSERT ... ON CONFLICT DO NOTHING.
    """
    conn = await asyncpg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_ADMIN_USER", "vault_admin"),
        password=os.environ["DB_ADMIN_PASSWORD"],
        database=os.getenv("DB_NAME", "ordersdb"),
        ssl="require",
    )

    try:
        await conn.execute("""
            INSERT INTO orders (id, customer_id, status) VALUES
            ('ORD-001', 'CUST-001', 'PENDING'),
            ('ORD-002', 'CUST-002', 'PENDING'),
            ('ORD-003', 'CUST-001', 'PENDING')
            ON CONFLICT DO NOTHING
        """)

        await conn.execute("""
            INSERT INTO inventory (product_id, product_name, quantity) VALUES
            ('PROD-A', 'Widget A', 100),
            ('PROD-B', 'Widget B', 50),
            ('PROD-C', 'Gadget C', 25),
            ('PROD-D', 'Gadget D', 10),
            ('PROD-E', 'Gizmo E', 5)
            ON CONFLICT DO NOTHING
        """)
    finally:
        await conn.close()


@activity.defn
async def rotate_vault_root_credentials() -> None:
    """
    Rotates the vault_admin password in Vault. After this, only Vault knows the password.
    Uses HCP Vault admin token from env vars.
    """
    vault_client = hvac.Client(
        url=os.environ["HCP_VAULT_ADDR"],
        token=os.environ["HCP_VAULT_TOKEN"],
        namespace=os.getenv("HCP_VAULT_NAMESPACE", "admin"),
    )

    vault_client.secrets.database.rotate_root_credentials(name="postgres-db")


# ── Compensation activities (Terraform destroy) ────────────────────────────────

@activity.defn
async def destroy_hcp_vault_config_module() -> None:
    """
    Destroys HCP Vault configuration (IAM auth, DB secrets engine, roles, policies).
    """
    run_terraform(
        _module_path("hcp_vault_config"),
        variables={},
        subcommand="destroy",
    )


@activity.defn
async def destroy_aws_infrastructure_module() -> None:
    """
    Destroys AWS infrastructure: VPC, subnets, security groups, NAT gateway, EC2, RDS, IAM role.
    """
    run_terraform(
        _module_path("aws_infrastructure"),
        variables={},
        subcommand="destroy",
    )


@activity.defn
async def destroy_hcp_vault_cluster_module() -> None:
    """
    Destroys HCP Vault cluster and HVN.
    """
    run_terraform(
        _module_path("hcp_vault_cluster"),
        variables={},
        subcommand="destroy",
    )


@activity.defn
async def destroy_temporal_cloud_module() -> None:
    """
    Destroys Temporal Cloud namespace and mTLS certificates.
    """
    run_terraform(
        _module_path("temporal_cloud"),
        variables={},
        subcommand="destroy",
    )
