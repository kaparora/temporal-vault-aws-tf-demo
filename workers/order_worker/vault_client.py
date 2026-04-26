import boto3
import hvac

from workers.order_worker.config import OrderWorkerConfig


def create_vault_client(cfg: OrderWorkerConfig) -> hvac.Client:
    client = hvac.Client(url=cfg.hcp_vault_addr, namespace=cfg.hcp_vault_namespace)

    if cfg.auth_method == "token":
        client.token = cfg.vault_token

    elif cfg.auth_method == "iam":
        # EC2 instance profile credentials are read automatically by boto3
        # from the instance metadata service — no static keys needed.
        session = boto3.Session()
        credentials = session.get_credentials().get_frozen_credentials()
        resp = client.auth.aws.iam_login(
            access_key=credentials.access_key,
            secret_key=credentials.secret_key,
            session_token=credentials.token,
            role=cfg.vault_role,
        )
        client.token = resp["auth"]["client_token"]

    else:
        raise ValueError(f"Unknown AUTH_METHOD: {cfg.auth_method!r}")

    if not client.is_authenticated():
        raise RuntimeError("Vault authentication failed")

    return client


def get_db_credentials(vault_client: hvac.Client, role: str) -> tuple[str, str]:
    secret = vault_client.secrets.database.generate_credentials(name=role)
    return secret["data"]["username"], secret["data"]["password"]
