#!/bin/bash
set -e

echo "========================================"
echo "Terraform Plan Validation Script"
echo "========================================"

# Load environment variables from .env
if [ -f .env ]; then
    set -a
    source .env
    set +a
else
    echo "ERROR: .env file not found"
    exit 1
fi

# Setup TF_VAR_* variables from .env
# Temporal Cloud API key (handle both file path and direct value)
if [ -f "$TEMPORAL_CLOUD_API_KEY" ]; then
    export TF_VAR_temporal_cloud_api_key=$(cat "$TEMPORAL_CLOUD_API_KEY" | tr -d '\n')
else
    export TF_VAR_temporal_cloud_api_key="$TEMPORAL_CLOUD_API_KEY"
fi

# HCP credentials
export TF_VAR_hcp_client_id="$HCP_CLIENT_ID"
export TF_VAR_hcp_client_secret="$HCP_CLIENT_SECRET"
export TF_VAR_hcp_project_id="$HCP_PROJECT_ID"

# AWS credentials (already in environment, but be explicit)
export TF_VAR_aws_access_key_id="$AWS_ACCESS_KEY_ID"
export TF_VAR_aws_secret_access_key="$AWS_SECRET_ACCESS_KEY"
export TF_VAR_aws_session_token="$AWS_SESSION_TOKEN"

# Database and deployment
export TF_VAR_db_admin_password="$DB_ADMIN_PASSWORD"
export TF_VAR_git_repo_url="$GIT_REPO_URL"
export TF_VAR_git_branch="${GIT_BRANCH:-main}"

# Terraform module variables (with defaults)
export TF_VAR_project_name="${PROJECT_NAME:-temporal-vault-aws-demo}"
export TF_VAR_aws_region="${AWS_REGION:-us-east-1}"
export TF_VAR_namespace_name="${TEMPORAL_NAMESPACE:-temporal-vault-demo}"
export TF_VAR_namespace_region="${TEMPORAL_NAMESPACE_REGION:-aws-us-east-1}"
export TF_VAR_cluster_id="${HCP_VAULT_CLUSTER_ID:-temporal-vault}"
export TF_VAR_cluster_tier="${HCP_VAULT_CLUSTER_TIER:-dev}"
export TF_VAR_hvn_region="${AWS_REGION:-us-east-1}"

#TERRAFORM_DIR="${TERRAFORM_DIR:-.}/terraform"

# Helper function to run terraform plan
run_terraform_plan() {
    local module_name=$1
    local module_path="$TERRAFORM_DIR/modules/$module_name"

    echo ""
    echo "========================================"
    echo "Module: $module_name"
    echo "========================================"

    if [ ! -d "$module_path" ]; then
        echo "ERROR: Module directory not found: $module_path"
        return 1
    fi

    cd "$module_path"

    echo "Running: terraform init"
    terraform init -no-color

    echo ""
    echo "Running: terraform plan"
    terraform plan -no-color

    cd - > /dev/null
}

# Test Module 1: Temporal Cloud (independent)
echo ""
echo "Testing Module 1: Temporal Cloud (independent)"
run_terraform_plan "temporal_cloud" || {
    echo "FAILED: temporal_cloud"
    exit 1
}

# Test Module 2: HCP Vault Cluster (independent)
echo ""
echo "Testing Module 2: HCP Vault Cluster (independent)"
run_terraform_plan "hcp_vault_cluster" || {
    echo "FAILED: hcp_vault_cluster"
    exit 1
}

echo ""
echo "========================================"
echo "Note: Modules 3 & 4 depend on outputs from 1 & 2"
echo "They will be validated when running the bootstrap workflow"
echo "========================================"
