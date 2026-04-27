from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workers.order_worker.activities.order_activities import OrderActivities


@dataclass
class OrderFulfillmentInput:
    order_id: str


NO_RETRY = RetryPolicy(maximum_attempts=1)

RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)


@workflow.defn
class OrderFulfillmentWorkflow:
    @workflow.run
    async def run(self, inp: OrderFulfillmentInput) -> str:
        order_id = inp.order_id
        inventory_reserved = False
        product_id = None
        quantity = None

        try:
            # Step 1: Validate order and read items
            validated = await workflow.execute_activity_method(
                OrderActivities.validate_order,
                order_id,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(seconds=30),
            )
            product_id = validated.item.product_id
            quantity = validated.item.quantity
            amount = validated.item.unit_price * quantity

            # Step 2: Reserve inventory
            await workflow.execute_activity_method(
                OrderActivities.reserve_inventory,
                args=[order_id, product_id, quantity],
                retry_policy=NO_RETRY,
                start_to_close_timeout=timedelta(seconds=30),
            )
            inventory_reserved = True

            # Step 3: Process payment
            await workflow.execute_activity_method(
                OrderActivities.process_payment,
                args=[order_id, amount],
                retry_policy=NO_RETRY,
                start_to_close_timeout=timedelta(seconds=30),
            )

            # Step 4: Mark order fulfilled
            await workflow.execute_activity_method(
                OrderActivities.update_order_status,
                order_id,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(seconds=30),
            )

            # Step 5: Send notification
            await workflow.execute_activity_method(
                OrderActivities.send_notification,
                args=[order_id, "ORDER_FULFILLED"],
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(seconds=30),
            )

            workflow.logger.info(f"Order {order_id} fulfilled successfully")
            return f"Order {order_id} fulfilled successfully"

        except Exception as e:
            workflow.logger.error(f"Order {order_id} failed: {e}")

            if inventory_reserved:
                workflow.logger.info(f"Compensating: releasing inventory for {order_id}")
                await workflow.execute_activity_method(
                    OrderActivities.release_inventory,
                    args=[order_id, product_id, quantity],
                    retry_policy=RETRY,
                    start_to_close_timeout=timedelta(seconds=30),
                )
                await workflow.execute_activity_method(
                    OrderActivities.send_notification,
                    args=[order_id, "ORDER_FAILED"],
                    retry_policy=RETRY,
                    start_to_close_timeout=timedelta(seconds=30),
                )

            raise
