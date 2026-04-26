terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ── Data sources ──────────────────────────────────────────────────────────────
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023*-x86_64"]
  }
}

# ── VPC ───────────────────────────────────────────────────────────────────────
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${var.project_name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project_name}-igw" }
}

# ── Subnets ───────────────────────────────────────────────────────────────────
# EC2 lives in a public subnet (needs outbound internet for Vault + Temporal Cloud)
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1)
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = { Name = "${var.project_name}-public" }
}

# RDS requires a subnet group spanning at least 2 AZs
resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 2)
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = { Name = "${var.project_name}-private-a" }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 3)
  availability_zone = data.aws_availability_zones.available.names[1]

  tags = { Name = "${var.project_name}-private-b" }
}

# ── Routing ───────────────────────────────────────────────────────────────────
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project_name}-public-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ── Security groups ───────────────────────────────────────────────────────────
resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-ec2-sg"
  description = "EC2 worker: outbound to internet and RDS"
  vpc_id      = aws_vpc.main.id

  # Outbound: HTTPS for HCP Vault + Temporal Cloud API
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HCP Vault + Temporal Cloud HTTPS"
  }

  # Outbound: Temporal Cloud gRPC
  egress {
    from_port   = 7233
    to_port     = 7233
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Temporal Cloud gRPC"
  }

  # Outbound: RDS PostgreSQL (within VPC)
  egress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.rds.id]
    description     = "RDS PostgreSQL"
  }

  # Outbound: HTTP for package installs (dnf, uv, git) at boot
  egress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP for package installs"
  }

  tags = { Name = "${var.project_name}-ec2-sg" }
}

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "RDS PostgreSQL: inbound from EC2 and bootstrap CIDR"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-rds-sg" }
}

# Inbound from EC2 — defined separately to avoid circular reference
resource "aws_security_group_rule" "rds_from_ec2" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ec2.id
  security_group_id        = aws_security_group.rds.id
  description              = "PostgreSQL from EC2 worker"
}

# Inbound from bootstrap machine (laptop) — only if CIDRs are provided
resource "aws_security_group_rule" "rds_from_bootstrap" {
  count             = length(var.bootstrap_allowed_cidrs) > 0 ? 1 : 0
  type              = "ingress"
  from_port         = 5432
  to_port           = 5432
  protocol          = "tcp"
  cidr_blocks       = var.bootstrap_allowed_cidrs
  security_group_id = aws_security_group.rds.id
  description       = "PostgreSQL from bootstrap machine"
}

# ── IAM role for EC2 ──────────────────────────────────────────────────────────
resource "aws_iam_role" "worker" {
  name = "${var.project_name}-worker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-worker-role" }
}

resource "aws_iam_instance_profile" "worker" {
  name = "${var.project_name}-worker-profile"
  role = aws_iam_role.worker.name
}

# ── RDS PostgreSQL ────────────────────────────────────────────────────────────
resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = { Name = "${var.project_name}-db-subnet-group" }
}

resource "aws_db_instance" "postgres" {
  identifier        = "${var.project_name}-postgres"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage

  db_name  = var.db_name
  username = var.db_admin_user
  password = var.db_admin_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = length(var.bootstrap_allowed_cidrs) > 0

  skip_final_snapshot = true
  deletion_protection = false

  tags = { Name = "${var.project_name}-postgres" }
}

# ── EC2 launch template ───────────────────────────────────────────────────────
resource "aws_launch_template" "worker" {
  name_prefix   = "${var.project_name}-worker-"
  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = var.ec2_instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.worker.name
  }

  network_interfaces {
    associate_public_ip_address = true
    security_groups             = [aws_security_group.ec2.id]
  }

  user_data = base64encode(templatefile("${path.module}/userdata.sh", {
    git_repo_url        = var.git_repo_url
    git_branch          = var.git_branch
    temporal_address    = var.temporal_address
    temporal_namespace  = var.temporal_namespace
    temporal_tls_cert   = var.temporal_tls_cert
    temporal_tls_key    = var.temporal_tls_key
    hcp_vault_addr      = var.hcp_vault_addr
    hcp_vault_namespace = var.hcp_vault_namespace
    vault_role          = var.vault_role
    task_queue          = var.task_queue
    db_host             = aws_db_instance.postgres.address
    db_name             = var.db_name
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.project_name}-worker" }
  }
}

# ── EC2 instance ──────────────────────────────────────────────────────────────
resource "aws_instance" "worker" {
  subnet_id = aws_subnet.public.id

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  tags = { Name = "${var.project_name}-worker" }
}
