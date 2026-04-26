import asyncio
import os
import sys

import structlog
from dotenv import load_dotenv

from workers.common.temporal_client import connect_temporal_client
from workers.infra_worker.workflows.bootstrap import BootstrapWorkflow

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
logger = structlog.get_logger()


async def main() -> None:
    load_dotenv()

    temporal_client = await connect_temporal_client(
        temporal_address=os.environ["TEMPORAL_ADDRESS"],
        temporal_namespace=os.environ["TEMPORAL_NAMESPACE"],
        tls_cert_path=os.environ["TEMPORAL_TLS_CERT"],
        tls_key_path=os.environ["TEMPORAL_TLS_KEY"],
    )

    bootstrap_task_queue = os.getenv("BOOTSTRAP_TASK_QUEUE", "bootstrap-tq")

    logger.info("triggering_bootstrap_workflow", task_queue=bootstrap_task_queue)
    try:
        await temporal_client.execute_workflow(
            BootstrapWorkflow.run,
            id="bootstrap-workflow",
            task_queue=bootstrap_task_queue,
        )
        logger.info("bootstrap_workflow_completed_successfully")
    except Exception as e:
        logger.error("bootstrap_workflow_failed", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
