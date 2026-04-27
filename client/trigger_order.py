import asyncio
import os
import sys

import structlog
from dotenv import load_dotenv

from workers.common.temporal_client import connect_temporal_client
from workers.order_worker.workflows.order_fulfillment import OrderFulfillmentInput, OrderFulfillmentWorkflow

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
logger = structlog.get_logger()


async def main() -> None:
    load_dotenv()

    if len(sys.argv) < 2:
        logger.error("usage: python -m client.trigger_order <order_id>")
        logger.error("example: python -m client.trigger_order ORD-001")
        sys.exit(1)

    order_id = sys.argv[1]

    temporal_client = await connect_temporal_client(
        temporal_address=os.environ["TEMPORAL_ADDRESS_ORDERS"],
        temporal_namespace=os.environ["TEMPORAL_NAMESPACE"],
        tls_cert_path=os.environ["TEMPORAL_TLS_CERT"],
        tls_key_path=os.environ["TEMPORAL_TLS_KEY"],
    )

    task_queue = os.getenv("ORDERS_TASK_QUEUE", "orders-tq")

    logger.info("triggering_order_fulfillment", order_id=order_id, task_queue=task_queue)
    try:
        result = await temporal_client.execute_workflow(
            OrderFulfillmentWorkflow,
            OrderFulfillmentInput(order_id=order_id),
            id=f"order-fulfillment-{order_id}",
            task_queue=task_queue,
        )
        logger.info("order_fulfilled", result=result)
    except Exception as e:
        logger.error("order_fulfillment_failed", order_id=order_id, error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
