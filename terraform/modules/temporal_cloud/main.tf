terraform {
  required_providers {
    temporalcloud = {
      source  = "temporalio/temporalcloud"
      version = "~> 0.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "temporalcloud" {
  api_key = var.temporal_cloud_api_key
}

# ── mTLS certificates ─────────────────────────────────────────────────────────
# Temporal Cloud uses mTLS to authenticate workers. We generate a self-signed
# CA, register it with the namespace, then generate a client cert/key signed
# by that CA. The client cert/key are written to the EC2 instance via userdata.

resource "tls_private_key" "ca" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "tls_self_signed_cert" "ca" {
  private_key_pem   = tls_private_key.ca.private_key_pem
  is_ca_certificate = true

  subject {
    common_name  = "${var.cert_org}-ca"
    organization = var.cert_org
  }

  validity_period_hours = var.cert_validity_hours

  allowed_uses = [
    "cert_signing",
    "crl_signing",
  ]
}

resource "tls_private_key" "client" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "tls_cert_request" "client" {
  private_key_pem = tls_private_key.client.private_key_pem

  subject {
    common_name  = "${var.cert_org}-worker"
    organization = var.cert_org
  }
}

resource "tls_locally_signed_cert" "client" {
  cert_request_pem   = tls_cert_request.client.cert_request_pem
  ca_private_key_pem = tls_private_key.ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.ca.cert_pem

  validity_period_hours = var.cert_validity_hours

  allowed_uses = [
    "client_auth",
  ]
}

# ── Temporal Cloud namespace ───────────────────────────────────────────────────
resource "temporalcloud_namespace" "main" {
  name           = var.namespace_name
  regions        = [var.namespace_region]
  retention_days = var.retention_days

  # Register the CA — any client presenting a cert signed by this CA is
  # authorised to connect to this namespace
  accepted_client_ca = base64encode(tls_self_signed_cert.ca.cert_pem)
}
