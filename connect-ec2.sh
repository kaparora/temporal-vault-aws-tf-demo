#!/bin/bash
set -euo pipefail

EC2_IP=$(cd terraform/modules/aws_infrastructure && terraform output -raw ec2_public_ip)
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=ip-address,Values=$EC2_IP" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text \
  --profile demo)

echo "Connecting to $INSTANCE_ID ($EC2_IP)..."
aws ssm start-session --target "$INSTANCE_ID" --profile demo
