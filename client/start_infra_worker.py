import asyncio
import os

import structlog
from dotenv import load_dotenv
from temporalio.worker import Worker

from workers.common.temporal_client import connect_temporal_client
from workers.infra_worker.activities.bootstrap_activities import (
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
from workers.infra_worker.workflows.bootstrap import BootstrapWorkflow

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
logger = structlog.get_logger()


async def main() -> None:
    load_dotenv()

    temporal_client = await connect_temporal_client(
        temporal_address=os.environ["TEMPORAL_ADDRESS_INFRA"],
        temporal_namespace=os.environ["TEMPORAL_NAMESPACE"],
        tls_cert_path=os.environ["TEMPORAL_TLS_CERT"],
        tls_key_path=os.environ["TEMPORAL_TLS_KEY"],
    )

    bootstrap_task_queue = os.getenv("BOOTSTRAP_TASK_QUEUE", "bootstrap-tq")
    worker = Worker(
        temporal_client,
        task_queue=bootstrap_task_queue,
        workflows=[BootstrapWorkflow],
        activities=[
            run_temporal_cloud_module,
            run_hcp_vault_cluster_module,
            run_aws_infrastructure_module,
            run_hcp_vault_config_module,
            create_db_schema,
            seed_db,
            rotate_vault_root_credentials,
            destroy_hcp_vault_config_module,
            destroy_aws_infrastructure_module,
            destroy_hcp_vault_cluster_module,
            destroy_temporal_cloud_module,
        ],
    )

    logger.info("starting_infra_worker", task_queue=bootstrap_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
