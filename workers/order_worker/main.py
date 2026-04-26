import asyncio
import socket

import structlog
from temporalio.worker import Worker

from workers.common.temporal_client import connect_temporal_client
from workers.order_worker.config import OrderWorkerConfig
from workers.order_worker.interceptors import VaultTokenRefreshInterceptor
from workers.order_worker.vault_client import create_vault_client

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
logger = structlog.get_logger()


async def main() -> None:
    cfg = OrderWorkerConfig()

    logger.info("authenticating_to_vault", auth_method=cfg.auth_method)
    vault_client = create_vault_client(cfg)
    logger.info("vault_authenticated")

    temporal_client = await connect_temporal_client(
        temporal_address=cfg.temporal_address,
        temporal_namespace=cfg.temporal_namespace,
        tls_cert_path=cfg.temporal_tls_cert,
        tls_key_path=cfg.temporal_tls_key,
    )

    identity = f"{socket.gethostname()}@{cfg.task_queue}"

    worker = Worker(
        temporal_client,
        task_queue=cfg.task_queue,
        workflows=[],    # populated in Step 8g
        activities=[],   # populated in Steps 8a-8f
        interceptors=[VaultTokenRefreshInterceptor(vault_client)],
        identity=identity,
        max_concurrent_activities=10,
    )

    logger.info("worker_starting", task_queue=cfg.task_queue, identity=identity)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
