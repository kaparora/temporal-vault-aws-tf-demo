import asyncio
import os

import structlog
from dotenv import load_dotenv

from workers.common.temporal_client import connect_temporal_client
from workers.infra_worker.workflows.teardown import TeardownInput, TeardownWorkflow

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
logger = structlog.get_logger()


async def main() -> None:
    load_dotenv()

    destroy_cluster = os.getenv("PROVISION_HCP_VAULT_CLUSTER", "true").lower() == "true"

    temporal_client = await connect_temporal_client(
        temporal_address=os.environ["TEMPORAL_ADDRESS_INFRA"],
        temporal_namespace=os.environ["TEMPORAL_NAMESPACE"],
        tls_cert_path=os.environ["TEMPORAL_TLS_CERT"],
        tls_key_path=os.environ["TEMPORAL_TLS_KEY"],
    )

    task_queue = os.getenv("BOOTSTRAP_TASK_QUEUE", "bootstrap-tq")

    logger.info("triggering_teardown", destroy_cluster=destroy_cluster, task_queue=task_queue)
    await temporal_client.execute_workflow(
        TeardownWorkflow,
        TeardownInput(destroy_cluster=destroy_cluster),
        id="teardown-workflow",
        task_queue=task_queue,
    )
    logger.info("teardown_complete")


if __name__ == "__main__":
    asyncio.run(main())
