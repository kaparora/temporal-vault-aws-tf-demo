# Demo Scope: Temporal Cloud + HCP Vault + AWS — Zero-Static-Credentials

## Overview

This demo implements a production-grade zero-static-credential pattern where:

1. **Bootstrap Workflow** (one-time): Orchestrates infrastructure setup via Terraform, configures HCP Vault and Temporal Cloud, initializes the database, and deploys the worker to EC2 as a systemd service.
2. **Order Fulfillment Workflow** (repeating): Runs on the deployed worker, executing the order fulfillment business logic with per-activity dynamic credentials from HCP Vault.

The worker runs on AWS EC2, authenticates to HCP Vault using its IAM instance profile (zero static credentials), and obtains short-lived PostgreSQL credentials for each activity.

**Stack:** Python 3.12 · Temporal Cloud · HCP Vault · AWS (EC2, RDS PostgreSQL, IAM) · Terraform · `uv` for dependency management

---

## Prerequisites

Before running this demo, you must have:

1. **HCP Vault account** — with organization and project created
2. **Temporal Cloud account** — with one namespace **manually created** (e.g., `bootstrap-ns`)
   - Temporal Cloud API key and secret (for Terraform provisioning)
3. **AWS account** — with credentials configured locally
4. **Laptop with:**
   - Python 3.12
   - `uv` (https://docs.astral.sh/uv/)
   - Terraform (https://www.terraform.io/)
   - Git

**Environment variables to set before running:**
```bash
export TEMPORAL_CLOUD_API_KEY=<your-api-key>
export TEMPORAL_CLOUD_API_SECRET=<your-api-secret>
export HCP_VAULT_ADDR=<your-hcp-vault-addr>
export HCP_VAULT_NAMESPACE=<your-hcp-namespace>
export HCP_VAULT_TOKEN=<your-hcp-token>
export AWS_ACCESS_KEY_ID=<your-aws-key>
export AWS_SECRET_ACCESS_KEY=<your-aws-secret>
export AWS_REGION=us-east-1
```

---

## Workflow Use Case: Order Fulfillment

### Why This Workflow

Order fulfilment is a textbook Temporal use case because it has:

- **Multiple sequential DB operations** — each step justifies its own short-lived credential
- **Real failure modes** — insufficient stock, payment failure, partial completion
- **Compensation logic** — if payment fails after inventory was reserved, inventory must be released
- **Durable execution value** — the worker can crash between steps and Temporal resumes from
  the last completed activity, not from the beginning

### Business Flow

A customer places an order. The system must:

1. Validate the order exists and is in `PENDING` state
2. Reserve inventory (decrement stock, mark reserved)
3. Process payment (write a payment record, simulate charge)
4. Mark the order `FULFILLED` and write a fulfilment record
5. Send a notification (write to a notifications queue table)

If **payment fails**, the workflow runs a compensation activity to release the reserved inventory
back to stock. If the **worker crashes** between steps 3 and 4, Temporal replays from step 4
(payment already succeeded — no double charge).

### Activity → Vault Credential Mapping

Each activity fetches a fresh dynamic credential from Vault just before touching the database.
The credential is scoped to the minimum permissions needed by that step.

| Activity | Vault DB Role | DB Permissions | Justification |
|---|---|---|---|
| `validate_order` | `role-read-orders` | `SELECT` on `orders` | Read-only check |
| `reserve_inventory` | `role-write-inventory` | `SELECT, UPDATE` on `inventory` | Needs to decrement stock |
| `process_payment` | `role-write-payments` | `INSERT` on `payments` | Write payment record only |
| `update_order_status` | `role-write-orders` | `UPDATE` on `orders`, `INSERT` on `fulfilments` | Mark fulfilled |
| `send_notification` | `role-write-notifications` | `INSERT` on `notifications` | Append-only |
| `release_inventory` *(compensation)* | `role-write-inventory` | `SELECT, UPDATE` on `inventory` | Undo reservation |

This demonstrates **least-privilege per activity** — a key security benefit of dynamic secrets
over a single shared connection pool.

### Workflow State Machine

```
START
  │
  ▼
[validate_order]──FAIL──► WorkflowError (order not found / not PENDING)
  │
  ▼
[reserve_inventory]──FAIL──► WorkflowError (out of stock)
  │
  ▼
[process_payment]──FAIL──► [release_inventory] ──► WorkflowError (payment declined)
  │
  ▼
[update_order_status]
  │
  ▼
[send_notification]
  │
  ▼
END (status: FULFILLED)
```

### Database Schema

```sql
-- orders: source of truth for order state
CREATE TABLE orders (
    id          TEXT PRIMARY KEY,
    customer    TEXT NOT NULL,
    product_id  TEXT NOT NULL,
    quantity    INT  NOT NULL,
    amount      NUMERIC(10,2) NOT NULL,
    status      TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | FULFILLED | FAILED
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- inventory: product stock levels
CREATE TABLE inventory (
    product_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    stock       INT  NOT NULL,
    reserved    INT  NOT NULL DEFAULT 0
);

-- payments: immutable payment log
CREATE TABLE payments (
    id          SERIAL PRIMARY KEY,
    order_id    TEXT NOT NULL,
    amount      NUMERIC(10,2) NOT NULL,
    status      TEXT NOT NULL,  -- SUCCESS | FAILED
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- fulfilments: fulfilment records
CREATE TABLE fulfilments (
    id          SERIAL PRIMARY KEY,
    order_id    TEXT NOT NULL,
    fulfilled_at TIMESTAMPTZ DEFAULT NOW()
);

-- notifications: outbox for downstream notification systems
CREATE TABLE notifications (
    id          SERIAL PRIMARY KEY,
    order_id    TEXT NOT NULL,
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### Sample Seed Data

```sql
INSERT INTO orders VALUES
    ('ORD-001', 'Alice', 'PROD-A', 2, 59.98, 'PENDING'),
    ('ORD-002', 'Bob',   'PROD-B', 1, 24.99, 'PENDING'),
    ('ORD-003', 'Carol', 'PROD-A', 5, 149.95, 'PENDING');

INSERT INTO inventory VALUES
    ('PROD-A', 'Hiking Boots', 10, 0),
    ('PROD-B', 'Trail Map',    3,  0);
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      HASHICORP CLOUD PLATFORM                        │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  HCP Vault (managed)                                         │   │
│  │  - AWS IAM auth method (EC2 instance profile)               │   │
│  │  - PostgreSQL database secrets engine                        │   │
│  │  - Dynamic DB roles (per-activity least-privilege)          │   │
│  │  - Policies: read creds, renew token                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ Vault API
                           │
┌──────────────────────────▼───────────────────────────────────────────┐
│                    TEMPORAL CLOUD (managed)                          │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Namespace: app-ns (created manually)                        │   │
│  │  Task Queues:                                                │   │
│  │    - bootstrap-tq (Bootstrap Workflow)                       │   │
│  │    - orders-tq (Order Fulfillment Workflow)                  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ gRPC poll
                           │
┌──────────────────────────▼───────────────────────────────────────────┐
│                   AWS (via Terraform)                                │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ RDS PostgreSQL (managed)                                    │   │
│  │ - Schema: orders, inventory, payments, fulfilments, ...     │   │
│  │ - Dynamic users created by Vault, revoked at lease TTL      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ EC2 Instance (t3.micro, IAM role: temporal-worker-role)     │   │
│  │ - systemd service: temporal-worker (starts on boot)         │   │
│  │                                                              │   │
│  │  Worker startup (systemd service):                          │   │
│  │    1. Read config from /etc/temporal-worker/.env            │   │
│  │    2. EC2 metadata → IAM creds → Vault AWS IAM login        │   │
│  │    3. Vault token obtained (TTL 1h)                         │   │
│  │    4. Temporal Cloud client connected                       │   │
│  │    5. Worker registered on orders-tq                        │   │
│  │                                                              │   │
│  │  Per activity execution:                                    │   │
│  │    - Interceptor: check Vault token TTL, renew if < 10m     │   │
│  │    - Activity: GET /database/creds/<role> from Vault        │   │
│  │    - Activity: asyncpg connect to RDS with dynamic creds    │   │
│  │    - Activity: execute query                                │   │
│  │    - Activity: close connection (Vault revokes at TTL)      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ VPC, Security Groups, NAT Gateway (for outbound to HCP)      │   │
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                    YOUR LAPTOP (client)                              │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Bootstrap Client (Python)                                   │   │
│  │  $ uv run python -m client.bootstrap                          │   │
│  │  → triggers Bootstrap Workflow (once)                         │   │
│  │                                                              │   │
│  │  Order Trigger Client (Python)                               │   │
│  │  $ uv run python -m client.trigger --order-id ORD-001        │   │
│  │  → triggers Order Fulfillment Workflow (repeating)           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Concern | Tool | Notes |
|---|---|---|
| Language | Python 3.12 | Async-first |
| Package manager | `uv` | Replaces pip + venv |
| **Temporal** | Temporal Cloud (managed) | Official Python SDK (`temporalio`) |
| **Vault** | HCP Vault (managed) | Official Python client (`hvac`) |
| **Database** | AWS RDS PostgreSQL (managed) | Serverless-friendly, auto-scaling |
| **Infrastructure** | Terraform | Modular provisioning: AWS, Vault config, Temporal config |
| AWS auth | `boto3` | EC2 IAM instance profile → Vault AWS auth |
| DB driver | `asyncpg` | Async PostgreSQL driver (matches asyncio worker) |
| Config | `python-dotenv` + env vars | `.env` template + environment variables |
| **Deployment** | systemd | Worker service on EC2, starts on boot |

---

## Repository Structure

```
temporal-vault-aws-demo/
│
├── README.md
├── pyproject.toml              ← uv-managed project + all dependencies
├── uv.lock                     ← lockfile (commit this)
├── .python-version             ← pins Python 3.12 for uv
├── .env.example                ← template for environment variables
│
├── terraform/                  ← Infrastructure as Code (modular)
│   ├── main.tf                 ← root module entrypoint
│   ├── terraform.tfvars.example ← template for Terraform variables
│   ├── outputs.tf              ← outputs: EC2 IP, RDS endpoint, Vault endpoints
│   │
│   ├── modules/
│   │   ├── aws_infrastructure/ ← EC2, RDS, VPC, IAM, Security Groups
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   ├── outputs.tf
│   │   │   └── userdata.sh     ← EC2 systemd service setup
│   │   │
│   │   ├── hcp_vault/          ← Vault configuration: auth, secrets engine, roles
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   │
│   │   └── temporal_cloud/     ← Temporal Cloud: namespace, task queues, certificates
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       └── outputs.tf
│
├── worker/
│   ├── __init__.py
│   ├── main.py                 ← entrypoint: startup sequence + worker.run()
│   ├── config.py               ← typed config from env vars
│   ├── vault_client.py         ← Vault auth (EC2 IAM) + credential fetch
│   ├── interceptors.py         ← VaultTokenRefreshInterceptor
│   │
│   └── workflows/
│       ├── __init__.py
│       ├── bootstrap.py        ← BootstrapWorkflow: one-time setup orchestration
│       └── order_fulfillment.py ← OrderFulfillmentWorkflow: business logic
│
├── worker/activities/
│   ├── __init__.py
│   ├── bootstrap_activities.py ← DB init, schema creation, seed data
│   └── order_activities.py     ← validate_order, reserve_inventory, process_payment, etc.
│
├── client/
│   ├── bootstrap.py            ← CLI to trigger BootstrapWorkflow (one-time)
│   └── trigger.py              ← CLI to trigger OrderFulfillmentWorkflow (repeating)
│
└── scripts/
    └── deploy-worker.sh        ← copies worker code to EC2 and restarts systemd
```

---

## Project Setup with uv

### Initialise

```bash
uv init temporal-vault-demo
cd temporal-vault-demo
echo "3.12" > .python-version
```

### `pyproject.toml`

```toml
[project]
name = "temporal-vault-demo"
version = "0.1.0"
description = "Temporal worker with HashiCorp Vault dynamic credentials on EC2"
requires-python = ">=3.12"

dependencies = [
    "temporalio>=1.7.0",
    "hvac>=2.3.0",
    "boto3>=1.34.0",
    "asyncpg>=0.29.0",
    "python-dotenv>=1.0.0",
    "structlog>=24.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
]

[tool.ruff]
line-length = 100
target-version = "py312"
```

### Install

```bash
uv sync                  # creates .venv + installs all deps
uv sync --extra dev      # also installs dev deps
```

### Run commands

```bash
uv run python -m worker.main          # start worker
uv run python -m client.trigger       # trigger workflow
uv run pytest                         # run tests
```

---

## Temporal Workflows in Detail

### Workflow 1: BootstrapWorkflow

**Trigger:** One-time, manually triggered from your laptop via `client.bootstrap`

**Activities:**
1. `create_db_schema()` — Creates all tables in RDS using Vault dynamic creds
2. `seed_db()` — Inserts sample orders and inventory
3. `start_worker_service()` — Starts the systemd service on EC2
4. (Future: validation activities to confirm everything is working)

**Inputs:** RDS endpoint, Vault role config, EC2 instance ID

**Output:** `{"status": "BOOTSTRAP_COMPLETE", "worker_ready": true}`

### Workflow 2: OrderFulfillmentWorkflow

**Trigger:** Repeating, triggered manually per order via `client.trigger --order-id ORD-001`

**Activities:**
1. `validate_order(order_id)` — Reads from orders table (role-read-orders)
2. `reserve_inventory(product_id, quantity)` — Updates inventory (role-write-inventory)
3. `process_payment(order_id, amount)` — Inserts payment record (role-write-payments)
4. `update_order_status(order_id)` — Marks order fulfilled (role-write-orders)
5. `send_notification(order_id, customer)` — Inserts notification (role-write-notifications)
6. `release_inventory(product_id, quantity)` — *(Compensation only)* Reverts reservation on payment failure

**Retry Policy:** 3 attempts per activity, 2-second initial backoff

**Compensation Logic:** If `process_payment` fails, execute `release_inventory` before failing the entire workflow

**Inputs:** `order_id: str`

**Output:** `{"order_id": "ORD-001", "status": "FULFILLED"}`

---

## Terraform Modules in Detail

### Module 1: aws_infrastructure

**Creates:**
- VPC with public/private subnets
- NAT gateway for EC2 → internet (HCP Vault/Temporal Cloud API calls)
- Security groups (EC2 ↔ RDS, EC2 → Vault/Temporal)
- RDS PostgreSQL instance (t3.micro, publicly accessible only to EC2)
- EC2 instance (t3.micro) with IAM instance profile
- IAM role `temporal-worker-role` with policies:
  - `sts:AssumeRole` for EC2
  - No hardcoded permissions; only used for IAM auth to Vault

**Outputs:**
- `ec2_public_ip`
- `rds_endpoint`
- `iam_role_arn` (for Vault AWS auth configuration)

**Userdata:** Installs `uv`, Python 3.12, systemd service template

### Module 2: hcp_vault

**Configures (via HCP API):**
- **Auth Methods:**
  - AWS IAM auth: bound to the EC2 instance's IAM role ARN
  - Allows EC2 to authenticate without any static credentials

- **Secrets Engine: Database**
  - Connection to RDS PostgreSQL
  - Admin credentials (vault_admin user created separately in RDS)
  - Dynamic roles for each activity:
    - `role-read-orders` → `SELECT` on `orders`
    - `role-write-inventory` → `SELECT, UPDATE` on `inventory`
    - `role-write-payments` → `INSERT` on `payments`
    - `role-write-orders` → `UPDATE` on `orders`, `INSERT` on `fulfilments`
    - `role-write-notifications` → `INSERT` on `notifications`

- **Policies:**
  - `temporal-worker-policy`: read all database credential paths + renew-self

**Outputs:**
- `vault_addr`
- `vault_namespace` (HCP)

### Module 3: temporal_cloud

**Configures (via Temporal Cloud API):**
- **Namespace:** Creates (or validates) the app namespace
- **Task Queues:**
  - `bootstrap-tq` for BootstrapWorkflow
  - `orders-tq` for OrderFulfillmentWorkflow
- **Worker Certificates:** Creates mutual TLS certs for worker-to-server authentication

**Outputs:**
- `temporal_address` (gRPC endpoint)
- `temporal_namespace`
- `ca_cert`, `client_cert`, `client_key` (for worker authentication)

---

## Configuration Files

### `.env.example`

```dotenv
# Temporal Cloud API (for Terraform provisioning)
TEMPORAL_CLOUD_API_KEY=<your-key>
TEMPORAL_CLOUD_API_SECRET=<your-secret>

# Temporal Cloud runtime (for worker + client)
TEMPORAL_ADDRESS=<your-ns>.account.tmprl.cloud:7233
TEMPORAL_NAMESPACE=app-ns

# HCP Vault
HCP_VAULT_ADDR=https://vault-prod-xxx.vault.hcp.cloud
HCP_VAULT_NAMESPACE=<your-hcp-namespace>
HCP_VAULT_TOKEN=<your-root-token>

# AWS (for EC2 IAM auth to Vault)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<your-key>
AWS_SECRET_ACCESS_KEY=<your-secret>

# Database (written by Terraform)
DB_HOST=<rds-endpoint>
DB_PORT=5432
DB_NAME=ordersdb
DB_ADMIN_USER=vault_admin
DB_ADMIN_PASSWORD=<generated-by-terraform>

# Worker identity (auto-set on EC2)
EC2_INSTANCE_ID=<auto-filled-by-terraform>
```

### `terraform.tfvars.example`

```hcl
aws_region              = "us-east-1"
ec2_instance_type       = "t3.micro"
rds_instance_class      = "db.t3.micro"
rds_allocated_storage   = 20

hcp_vault_addr          = "https://vault-prod-xxx.vault.hcp.cloud"
hcp_vault_namespace     = "your-hcp-namespace"

temporal_cloud_api_key  = "your-api-key"
temporal_cloud_api_secret = "your-api-secret"
temporal_namespace      = "app-ns"

project_name            = "temporal-vault-aws-demo"
```

---

## Execution Flow

### Step 1: Provision Infrastructure with Terraform

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # fill in your values
terraform init
terraform plan
terraform apply
```

**What Terraform creates:**
- AWS VPC, subnets, security groups, NAT gateway
- RDS PostgreSQL instance
- EC2 instance (t3.micro) with IAM role `temporal-worker-role`
- HCP Vault AWS auth method (bound to the EC2 IAM role)
- HCP Vault database secrets engine + dynamic DB roles (per-activity)
- Terraform outputs EC2 IP, RDS endpoint, Vault addresses

### Step 2: Deploy Worker Code to EC2

```bash
# Copy this repo to EC2
scp -r . ec2-user@<EC2_IP>:/opt/temporal-worker
ssh ec2-user@<EC2_IP>
cd /opt/temporal-worker
uv sync
```

### Step 3: Run Bootstrap Workflow (One-Time Setup)

```bash
# Set environment variables
export TEMPORAL_CLOUD_API_KEY=<your-key>
export TEMPORAL_CLOUD_API_SECRET=<your-secret>
export HCP_VAULT_ADDR=<from-terraform-output>
export HCP_VAULT_TOKEN=<your-token>
export TEMPORAL_ADDRESS=<from-terraform-output>
export TEMPORAL_NAMESPACE=<from-terraform-output>

# Trigger bootstrap (from your laptop)
uv run python -m client.bootstrap
```

**BootstrapWorkflow orchestrates:**
1. Database schema creation and seed data
2. Vault configuration (auth methods, roles, policies)
3. Starting the worker systemd service on EC2

### Step 4: Trigger Order Fulfillment Workflows (Repeating)

```bash
# From your laptop
uv run python -m client.trigger --order-id ORD-001
uv run python -m client.trigger --order-id ORD-002
```

**OrderFulfillmentWorkflow executes:**
1. Validate order
2. Reserve inventory
3. Process payment (with automatic compensation if it fails)
4. Update order status
5. Send notification

---

## Testing Checklist

### Bootstrap Workflow
- [ ] Bootstrap workflow completes without errors
- [ ] RDS database schema is created
- [ ] Seed data is inserted
- [ ] Worker systemd service starts on EC2
- [ ] Temporal Cloud shows worker registered on `orders-tq`

### Order Fulfillment Workflow
- [ ] All activities complete in correct sequence for a PENDING order
- [ ] Workflow shows `status: FULFILLED`
- [ ] Fails correctly for non-existent orders
- [ ] Insufficient stock fails correctly
- [ ] Payment failure triggers compensation (`release_inventory`)
- [ ] HCP Vault shows distinct leases for each activity's dynamic credential
- [ ] Leases expire after configured TTL
- [ ] Running same order ID twice fails (Temporal deduplication)

### Security Validation
- [ ] EC2 has no static database credentials (only IAM)
- [ ] HCP Vault audit log shows EC2 IAM principal ARN as authenticated identity
- [ ] RDS has no superuser credentials; only dynamic users with minimal grants
- [ ] No AWS secret keys or Vault tokens logged to stdout

---

## References

- Temporal Python SDK Workers: https://docs.temporal.io/develop/python/workers
- hvac AWS IAM auth: https://hvac.readthedocs.io/en/stable/usage/auth_methods/aws.html
- Vault Database Secrets Engine: https://developer.hashicorp.com/vault/docs/secrets/database/postgresql
- Vault AWS Auth Method: https://developer.hashicorp.com/vault/docs/auth/aws
- Temporal Python SDK samples: https://github.com/temporalio/samples-python
- asyncpg docs: https://magicstack.github.io/asyncpg/current/
- uv docs: https://docs.astral.sh/uv/
