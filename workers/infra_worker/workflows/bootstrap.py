import os
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from workers.infra_worker.activities.bootstrap_activities import (
    AWSInfraInput,
    HCPVaultClusterOutput,
    HCPVaultConfigInput,
    create_db_schema,
    destroy_aws_infrastructure_module,
    destroy_hcp_vault_cluster_module,
    destroy_hcp_vault_config_module,
    destroy_temporal_cloud_module,
    rotate_vault_root_credentials,
    run_aws_infrastructure_module,
    run_hcp_vault_cluster_module,
    run_hcp_vault_config_module,
    run_temporal_cloud_module,
    seed_db,
)
from workers.infra_worker.config import DEFAULT_MAX_ACTIVITY_RETRIES


@workflow.defn
class BootstrapWorkflow:
    """
    Orchestrates full infrastructure bootstrap:
    1. Temporal Cloud (namespace + mTLS certs)
    2. HCP Vault cluster + HVN
    3. AWS infrastructure (VPC, EC2, RDS, IAM)
    4. Vault configuration (IAM auth, DB secrets engine, roles)
    5. Database schema creation
    6. Database seeding with sample data
    7. Vault root credential rotation

    If any step fails after max retries, full rollback (destroy all Terraform modules).
    """

    @workflow.run
    async def run(self) -> None:
        retry_policy = RetryPolicy(
            max_attempts=DEFAULT_MAX_ACTIVITY_RETRIES + 1,
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            max_interval=timedelta(seconds=60),
        )

        try:
            # Step 1: Provision Temporal Cloud
            temporal_output = await workflow.execute_activity(
                run_temporal_cloud_module,
                retry_policy=retry_policy,
            )

            # Step 2: Provision HCP Vault cluster (or use existing)
            provision_cluster = os.getenv("PROVISION_HCP_VAULT_CLUSTER", "true").lower() == "true"
            if provision_cluster:
                vault_output = await workflow.execute_activity(
                    run_hcp_vault_cluster_module,
                    retry_policy=retry_policy,
                )
                workflow.logger.info("hcp_vault_cluster_provisioned")
            else:
                vault_output = HCPVaultClusterOutput(
                    vault_public_endpoint=os.environ["HCP_VAULT_ADDR"],
                    vault_namespace=os.getenv("HCP_VAULT_NAMESPACE", "admin"),
                    admin_token=os.environ["HCP_VAULT_TOKEN"],
                )
                workflow.logger.info("using_existing_hcp_vault_cluster")

            # Step 3: Provision AWS infrastructure
            aws_output = await workflow.execute_activity(
                run_aws_infrastructure_module,
                AWSInfraInput(
                    temporal_address=temporal_output.temporal_address,
                    temporal_namespace=temporal_output.temporal_namespace,
                    temporal_tls_cert=temporal_output.client_cert,
                    temporal_tls_key=temporal_output.client_key,
                    hcp_vault_addr=vault_output.vault_public_endpoint,
                    hcp_vault_namespace=vault_output.vault_namespace,
                ),
                retry_policy=retry_policy,
            )

            # Step 4: Configure Vault
            await workflow.execute_activity(
                run_hcp_vault_config_module,
                HCPVaultConfigInput(
                    vault_public_endpoint=vault_output.vault_public_endpoint,
                    vault_namespace=vault_output.vault_namespace,
                    admin_token=vault_output.admin_token,
                    iam_role_arn=aws_output.iam_role_arn,
                    rds_host=aws_output.rds_host,
                ),
                retry_policy=retry_policy,
            )

            # Step 5: Create database schema
            await workflow.execute_activity(
                create_db_schema,
                retry_policy=retry_policy,
            )

            # Step 6: Seed database with sample data
            await workflow.execute_activity(
                seed_db,
                retry_policy=retry_policy,
            )

            # Step 7: Rotate Vault root credentials
            await workflow.execute_activity(
                rotate_vault_root_credentials,
                retry_policy=retry_policy,
            )

        except Exception as e:
            workflow.logger.error(f"Bootstrap failed at step, rolling back all infrastructure: {e}")

            # Full rollback: destroy all Terraform modules in reverse order
            # (safe to call even if modules weren't fully created)
            await workflow.execute_activity(
                destroy_hcp_vault_config_module,
                retry_policy=retry_policy,
            )
            await workflow.execute_activity(
                destroy_aws_infrastructure_module,
                retry_policy=retry_policy,
            )

            # Only destroy cluster if we provisioned it
            if provision_cluster:
                await workflow.execute_activity(
                    destroy_hcp_vault_cluster_module,
                    retry_policy=retry_policy,
                )

            await workflow.execute_activity(
                destroy_temporal_cloud_module,
                retry_policy=retry_policy,
            )
            raise
