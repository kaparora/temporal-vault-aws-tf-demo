terraform {
  required_providers {
    hcp = {
      source  = "hashicorp/hcp"
      version = "~> 0.82"
    }
  }
}

provider "hcp" {
  client_id     = var.hcp_client_id
  client_secret = var.hcp_client_secret
  project_id    = var.hcp_project_id
}

# HVN is a required network container for every HCP Vault cluster.
# For this demo we don't peer it with the AWS VPC — EC2 connects to
# Vault over the public internet via HTTPS.
resource "hcp_hvn" "main" {
  hvn_id         = "${var.project_name}-hvn"
  cloud_provider = "aws"
  region         = var.hvn_region
  cidr_block     = var.hvn_cidr
}

resource "hcp_vault_cluster" "main" {
  cluster_id = var.cluster_id
  hvn_id     = hcp_hvn.main.hvn_id
  tier       = var.cluster_tier

  # Public endpoint so EC2 can reach Vault over the internet
  public_endpoint = true
}

# Short-lived admin token used only by the hcp_vault_config module to
# configure auth methods, secrets engines, and policies.
resource "hcp_vault_cluster_admin_token" "main" {
  cluster_id = hcp_vault_cluster.main.cluster_id
}
