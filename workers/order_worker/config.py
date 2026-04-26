import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class OrderWorkerConfig:
    # ── Temporal Cloud ────────────────────────────────────────────────────────
    temporal_address: str   = os.getenv("TEMPORAL_ADDRESS", "")
    temporal_namespace: str = os.getenv("TEMPORAL_NAMESPACE", "default")
    temporal_tls_cert: str  = os.getenv("TEMPORAL_TLS_CERT", "")
    temporal_tls_key: str   = os.getenv("TEMPORAL_TLS_KEY", "")

    # ── HCP Vault ─────────────────────────────────────────────────────────────
    hcp_vault_addr: str      = os.getenv("HCP_VAULT_ADDR", "")
    hcp_vault_namespace: str = os.getenv("HCP_VAULT_NAMESPACE", "admin")
    vault_role: str          = os.getenv("VAULT_ROLE", "temporal-worker")
    auth_method: str         = os.getenv("AUTH_METHOD", "iam")   # iam | token
    vault_token: str         = os.getenv("HCP_VAULT_TOKEN", "")  # local only

    # ── Worker ────────────────────────────────────────────────────────────────
    task_queue: str = os.getenv("ORDERS_TASK_QUEUE", "orders-tq")

    # ── Database ──────────────────────────────────────────────────────────────
    db_host: str  = os.getenv("DB_HOST", "")
    db_port: int  = int(os.getenv("DB_PORT", "5432"))
    db_name: str  = os.getenv("DB_NAME", "ordersdb")
