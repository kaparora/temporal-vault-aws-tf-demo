from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from workers.infra_worker.activities.bootstrap_activities import (
    destroy_aws_infrastructure_module,
    destroy_hcp_vault_cluster_module,
    destroy_temporal_cloud_module,
)
from workers.infra_worker.config import DEFAULT_MAX_ACTIVITY_RETRIES


@dataclass
class TeardownInput:
    destroy_cluster: bool = True  # set False to keep the HCP Vault cluster


@workflow.defn
class TeardownWorkflow:
    """
    Destroys all infrastructure provisioned by BootstrapWorkflow, in reverse order:
    1. AWS infrastructure (EC2, RDS, VPC, IAM)
    2. HCP Vault cluster (Vault config destroyed with it)
    3. Temporal Cloud namespace + mTLS certs

    Set destroy_cluster=False to skip step 2 (e.g. if you reused an existing cluster).
    """

    @workflow.run
    async def run(self, inp: TeardownInput) -> None:
        retry_policy = RetryPolicy(
            maximum_attempts=DEFAULT_MAX_ACTIVITY_RETRIES + 1,
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=60),
        )

        workflow.logger.info("starting_teardown", destroy_cluster=inp.destroy_cluster)

        await workflow.execute_activity(
            destroy_aws_infrastructure_module,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=30),
        )
        workflow.logger.info("step_1_complete: AWS infrastructure destroyed")

        if inp.destroy_cluster:
            await workflow.execute_activity(
                destroy_hcp_vault_cluster_module,
                retry_policy=retry_policy,
                start_to_close_timeout=timedelta(minutes=30),
            )
            workflow.logger.info("step_2_complete: HCP Vault cluster destroyed")
        else:
            workflow.logger.info("step_2_skipped: keeping existing HCP Vault cluster")

        await workflow.execute_activity(
            destroy_temporal_cloud_module,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=30),
        )
        workflow.logger.info("step_3_complete: Temporal Cloud namespace destroyed")

        workflow.logger.info("teardown_complete")
