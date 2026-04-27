# Temporal Cloud + HCP Vault + AWS Terraform Demo

**Status: Bootstrap Working — Order Fulfillment In Progress**

A production-grade demonstration of zero-static-credentials infrastructure using:
- **Temporal Cloud** for workflow orchestration
- **HCP Vault** for secrets management and dynamic credentials
- **AWS** for compute and database infrastructure
- **Terraform** for Infrastructure as Code

## Overview

This project demonstrates how to build a secure, credential-free system where:

1. **Bootstrap Workflow** (runs on laptop) orchestrates all infrastructure provisioning via Terraform activities
2. **Order Fulfillment Workflow** (runs on EC2) processes orders using per-activity dynamic database credentials from Vault
3. **EC2 IAM Authentication** eliminates static credentials — workers authenticate to Vault using their IAM role
4. **Vault Root Credential Rotation** removes the static database admin password after initial setup

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Temporal Cloud                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Bootstrap Workflow (Laptop)                       │  │
│  │  1. Provision Temporal Cloud namespace            │  │
│  │  2. Provision HCP Vault cluster                   │  │
│  │  3. Provision AWS infrastructure (EC2, RDS, IAM)  │  │
│  │  4. Configure Vault (IAM auth, DB engine, roles)  │  │
│  │  5. Create database schema                        │  │
│  │  6. Seed database                                 │  │
│  │  7. Rotate Vault root credentials                 │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Order Fulfillment Workflow (EC2)                  │  │
│  │  - Validate order                                 │  │
│  │  - Reserve inventory (dynamic DB creds from Vault)│  │
│  │  - Process payment                                │  │
│  │  - Update order status                            │  │
│  │  - Send notification                              │  │
│  │  - Release inventory (compensation)               │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
        ↓                    ↓                    ↓
    HCP Vault          AWS Infrastructure      RDS PostgreSQL
    (mTLS, IAM)      (EC2 with IAM role)      (no static creds)
```

## Key Features

- **Zero Static Credentials**: EC2 workers use IAM role for Vault authentication
- **Dynamic Secrets**: Each activity gets fresh, short-lived database credentials
- **Terraform Orchestration**: Infrastructure provisioning is a Temporal workflow, not a shell script
- **Retry & Compensation**: Failed activities retry automatically; full rollback on final failure
- **Production-Ready**: mTLS authentication, encrypted state, audit trails

## Prerequisites

- HCP account with Vault
- Temporal Cloud account (with one manually-created namespace)
- AWS account
- Python 3.12 + uv
- Terraform
- GitHub account (for code deployment to EC2)

## Getting Started

**This is still WIP — full documentation coming soon.**

See `.env.example` for required environment variables.

## Project Structure

```
.
├── terraform/modules/              # Terraform modules (independent, run as activities)
│   ├── temporal_cloud/             # Provisions Temporal Cloud namespace + certs
│   ├── hcp_vault_cluster/          # Provisions HCP Vault cluster + HVN
│   ├── aws_infrastructure/         # Provisions VPC, EC2, RDS, IAM
│   └── hcp_vault_config/           # Configures Vault (IAM auth, DB engine, roles)
├── workers/
│   ├── infra_worker/               # Bootstrap workflow & activities
│   │   ├── workflows/bootstrap.py  # Orchestrates all 7 bootstrap steps
│   │   ├── activities/bootstrap_activities.py
│   │   └── terraform_runner.py
│   └── order_worker/               # Order fulfillment workflow & activities
│       ├── workflows/order_fulfillment.py
│       ├── activities/order_activities.py
│       └── vault_client.py         # Vault IAM auth & credential fetching
├── client/
│   ├── start_infra_worker.py       # Starts bootstrap worker
│   └── start_bootstrap_workflow.py  # Triggers bootstrap workflow
└── test_terraform_plans.sh         # Validates Terraform configurations
```

## Current Status

### Bootstrap Workflow ✅
All 7 bootstrap steps are working end-to-end and can be rerun without issues:
- A fresh random DB admin password is generated on each run (RDS-compatible charset)
- Schema creation and seeding are idempotent (`CREATE TABLE IF NOT EXISTS`, `INSERT ... ON CONFLICT DO NOTHING`)
- Vault root credential rotation runs after schema setup, eliminating the static password
- Because Terraform state is preserved between runs, the workflow is safe to fix and rerun — Terraform will only apply changes

**Compensation (rollback) activities** exist for all Terraform modules (`destroy_*` activities) but are currently commented out in the workflow. Wiring up full automatic rollback on failure is a pending task.

### Order Fulfillment Workflow ⬜
Not yet implemented.

## Next Steps

- [ ] Implement order fulfillment workflow and activities (dynamic Vault creds per activity)
- [ ] Wire up compensation/rollback in bootstrap workflow on failure
- [ ] Security hardening (Temporal data converter, S3 remote state, AWS Secrets Manager)

---

**Questions?** This project is under active development. Check back for updates!
