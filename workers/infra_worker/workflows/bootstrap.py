from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from workers.infra_worker.activities.bootstrap_activities import (
    AWSInfraInput,
    DBActivityInput,
    HCPVaultClusterOutput,
    HCPVaultConfigInput,
    VaultRotateInput,
    create_db_schema,
    destroy_aws_infrastructure_module,
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


@dataclass
class BootstrapInput:
    provision_cluster: bool
    hcp_vault_addr: str = ""
    hcp_vault_namespace: str = "admin"
    hcp_vault_token: str = ""


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
    async def run(self, inp: BootstrapInput) -> None:
        retry_policy = RetryPolicy(
            maximum_attempts=DEFAULT_MAX_ACTIVITY_RETRIES + 1,
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=60),
        )

        try:
            # Step 1: Provision Temporal Cloud
            temporal_output = await workflow.execute_activity(
                run_temporal_cloud_module,
                retry_policy=retry_policy,
                start_to_close_timeout=timedelta(minutes=30),
            )
            workflow.logger.info(f"step_1_complete: {temporal_output.temporal_address_orders}")

            # Step 2: Provision HCP Vault cluster (or use existing)
            if inp.provision_cluster:
                vault_output = await workflow.execute_activity(
                    run_hcp_vault_cluster_module,
                    retry_policy=retry_policy,
                    start_to_close_timeout=timedelta(minutes=30),
                )
                workflow.logger.info("hcp_vault_cluster_provisioned")
            else:
                vault_output = HCPVaultClusterOutput(
                    vault_public_endpoint=inp.hcp_vault_addr,
                    vault_namespace=inp.hcp_vault_namespace,
                    admin_token=inp.hcp_vault_token,
                )
                workflow.logger.info("using_existing_hcp_vault_cluster")

            workflow.logger.info(f"step_2_complete: {vault_output.vault_public_endpoint}")

            # Step 3: Provision AWS infrastructure
            aws_output = await workflow.execute_activity(
                run_aws_infrastructure_module,
                AWSInfraInput(
                    temporal_address_orders=temporal_output.temporal_address_orders,
                    temporal_namespace=temporal_output.temporal_namespace,
                    temporal_tls_cert=temporal_output.client_cert,
                    temporal_tls_key=temporal_output.client_key,
                    hcp_vault_addr=vault_output.vault_public_endpoint,
                    hcp_vault_namespace=vault_output.vault_namespace,
                ),
                retry_policy=retry_policy,
                start_to_close_timeout=timedelta(minutes=30),
            )
            workflow.logger.info(f"step_3_complete: EC2={aws_output.ec2_public_ip}, RDS={aws_output.rds_host}")

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
                start_to_close_timeout=timedelta(minutes=30),
            )
            workflow.logger.info("step_4_complete")

            # Step 5: Create database schema
            await workflow.execute_activity(
                create_db_schema,
                DBActivityInput(
                    rds_host=aws_output.rds_host,
                    db_port=5432,
                    db_admin_user="postgres",
                    db_name="ordersdb",
                ),
                retry_policy=retry_policy,
                start_to_close_timeout=timedelta(minutes=10),
            )
            workflow.logger.info("step_5_complete")

            # Step 6: Seed database with sample data
            await workflow.execute_activity(
                seed_db,
                DBActivityInput(
                    rds_host=aws_output.rds_host,
                    db_port=5432,
                    db_admin_user="postgres",
                    db_name="ordersdb",
                ),
                retry_policy=retry_policy,
                start_to_close_timeout=timedelta(minutes=10),
            )
            workflow.logger.info("step_6_complete")

            # Step 7: Rotate Vault root credentials
            await workflow.execute_activity(
                rotate_vault_root_credentials,
                VaultRotateInput(
                    vault_public_endpoint=vault_output.vault_public_endpoint,
                    vault_namespace=vault_output.vault_namespace,
                    admin_token=vault_output.admin_token,
                ),
                retry_policy=retry_policy,
                start_to_close_timeout=timedelta(minutes=10),
            )
            workflow.logger.info("step_7_complete")

        except Exception as e:
            workflow.logger.error(f"Destroy failed: {e}")
            raise

            # # Cleanup on failure
            # try:
            #     await workflow.execute_activity(
            #         destroy_hcp_vault_config_module,
            #         vault_output,
            #         retry_policy=retry_policy,
            #         start_to_close_timeout=timedelta(minutes=30),
            #     )
            # except NameError:
            #     workflow.logger.info("Vault not provisioned, skipping Vault config destroy")

            # await workflow.execute_activity(
            #     destroy_aws_infrastructure_module,
            #     retry_policy=retry_policy,
            #     start_to_close_timeout=timedelta(minutes=30),
            # )

            # # # Only destroy cluster if we provisioned it
            # # if provision_cluster:
            # #     await workflow.execute_activity(
            # #         destroy_hcp_vault_cluster_module,
            # #         retry_policy=retry_policy,
            # #         start_to_close_timeout=timedelta(minutes=30),
            # #     )

            # # await workflow.execute_activity(
            # #     destroy_temporal_cloud_module,
            # #     retry_policy=retry_policy,
            # #     start_to_close_timeout=timedelta(minutes=30),
            # # )
            # raise
