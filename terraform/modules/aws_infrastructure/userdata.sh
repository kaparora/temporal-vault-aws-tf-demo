#!/bin/bash
set -euo pipefail

# ── System packages ───────────────────────────────────────────────────────────
dnf update -y
dnf install -y git python3.12 python3.12-pip

# ── Install uv ────────────────────────────────────────────────────────────────
curl -LsSf https://astral.sh/uv/install.sh | sh
source /root/.local/bin/env
cp /root/.local/bin/uv /usr/local/bin/uv

# ── Clone worker code ─────────────────────────────────────────────────────────
git clone --branch ${git_branch} ${git_repo_url} /opt/temporal-worker
cd /opt/temporal-worker
uv sync

# ── TLS certificates for Temporal Cloud ──────────────────────────────────────
mkdir -p /opt/temporal-worker/certs
cat > /opt/temporal-worker/certs/client.pem << 'CERT'
${temporal_tls_cert}
CERT

cat > /opt/temporal-worker/certs/client.key << 'KEY'
${temporal_tls_key}
KEY
chmod 600 /opt/temporal-worker/certs/client.key

# ── Worker .env ───────────────────────────────────────────────────────────────
cat > /opt/temporal-worker/.env << 'EOF'
AUTH_METHOD=iam
TEMPORAL_ADDRESS=${temporal_address}
TEMPORAL_NAMESPACE=${temporal_namespace}
TEMPORAL_TLS_CERT=/opt/temporal-worker/certs/client.pem
TEMPORAL_TLS_KEY=/opt/temporal-worker/certs/client.key
HCP_VAULT_ADDR=${hcp_vault_addr}
HCP_VAULT_NAMESPACE=${hcp_vault_namespace}
VAULT_ROLE=${vault_role}
TASK_QUEUE=${task_queue}
DB_HOST=${db_host}
DB_PORT=5432
DB_NAME=${db_name}
EOF
chmod 600 /opt/temporal-worker/.env

# ── Fix ownership ─────────────────────────────────────────────────────────────
chown -R ec2-user:ec2-user /opt/temporal-worker

# ── Systemd service ───────────────────────────────────────────────────────────
cat > /etc/systemd/system/temporal-worker.service << 'SERVICE'
[Unit]
Description=Temporal Order Fulfillment Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/temporal-worker
EnvironmentFile=/opt/temporal-worker/.env
ExecStartPre=/usr/bin/git -C /opt/temporal-worker pull
ExecStartPre=/usr/local/bin/uv sync --project /opt/temporal-worker
ExecStart=/opt/temporal-worker/.venv/bin/python -m workers.order_worker.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable temporal-worker
systemctl start temporal-worker
