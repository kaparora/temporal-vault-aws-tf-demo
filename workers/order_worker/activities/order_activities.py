import uuid
from dataclasses import dataclass

import asyncpg
from temporalio import activity

from workers.order_worker.config import OrderWorkerConfig
from workers.order_worker.vault_client import get_db_credentials


@dataclass
class OrderItem:
    product_id: str
    quantity: int
    unit_price: float


@dataclass
class ValidateOrderResult:
    order_id: str
    customer_id: str
    item: OrderItem


class OrderActivities:
    def __init__(self, cfg: OrderWorkerConfig, vault_client):
        self.cfg = cfg
        self.vault_client = vault_client

    async def _connect(self, role: str) -> asyncpg.Connection:
        username, password = get_db_credentials(self.vault_client, role)
        return await asyncpg.connect(
            host=self.cfg.db_host,
            port=self.cfg.db_port,
            user=username,
            password=password,
            database=self.cfg.db_name,
            ssl="require",
        )

    @activity.defn
    async def validate_order(self, order_id: str) -> ValidateOrderResult:
        activity.logger.info(f"Validating order {order_id}")
        conn = await self._connect("role-read-orders")
        try:
            order = await conn.fetchrow(
                "SELECT id, customer_id, status FROM orders WHERE id = $1", order_id
            )
            if not order:
                raise ValueError(f"Order {order_id} not found")
            if order["status"] != "PENDING":
                raise ValueError(f"Order {order_id} is not PENDING (status={order['status']})")

            item = await conn.fetchrow(
                "SELECT product_id, quantity, unit_price FROM order_items WHERE order_id = $1",
                order_id,
            )
            if not item:
                raise ValueError(f"No items found for order {order_id}")

            activity.logger.info(f"Order {order_id} validated: product={item['product_id']} qty={item['quantity']}")
            return ValidateOrderResult(
                order_id=order_id,
                customer_id=order["customer_id"],
                item=OrderItem(
                    product_id=item["product_id"],
                    quantity=item["quantity"],
                    unit_price=float(item["unit_price"]),
                ),
            )
        finally:
            await conn.close()

    @activity.defn
    async def reserve_inventory(self, order_id: str, product_id: str, quantity: int) -> None:
        activity.logger.info(f"Reserving inventory: order={order_id} product={product_id} qty={quantity}")
        conn = await self._connect("role-write-inventory")
        try:
            result = await conn.execute(
                """
                UPDATE inventory SET quantity = quantity - $1, updated_at = NOW()
                WHERE product_id = $2 AND quantity >= $1
                """,
                quantity,
                product_id,
            )
            rows_affected = int(result.split()[-1])
            if rows_affected == 0:
                raise ValueError(f"Insufficient stock for product {product_id} (requested {quantity})")
            activity.logger.info(f"Inventory reserved: product={product_id} qty={quantity}")
        finally:
            await conn.close()

    @activity.defn
    async def process_payment(self, order_id: str, amount: float) -> str:
        activity.logger.info(f"Processing payment: order={order_id} amount={amount}")

        if order_id == "ORD-003":
            raise ValueError(f"Payment declined for order {order_id}")

        conn = await self._connect("role-write-payments")
        try:
            payment_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"
            await conn.execute(
                """
                INSERT INTO payments (id, order_id, amount, status)
                VALUES ($1, $2, $3, 'SUCCESS')
                """,
                payment_id,
                order_id,
                amount,
            )
            activity.logger.info(f"Payment successful: payment_id={payment_id}")
            return payment_id
        finally:
            await conn.close()

    @activity.defn
    async def update_order_status(self, order_id: str) -> None:
        activity.logger.info(f"Updating order status: order={order_id}")
        conn = await self._connect("role-write-orders")
        try:
            await conn.execute(
                "UPDATE orders SET status = 'FULFILLED', updated_at = NOW() WHERE id = $1",
                order_id,
            )
            fulfilment_id = f"FUL-{uuid.uuid4().hex[:8].upper()}"
            await conn.execute(
                """
                INSERT INTO fulfilments (id, order_id, status)
                VALUES ($1, $2, 'COMPLETED')
                """,
                fulfilment_id,
                order_id,
            )
            activity.logger.info(f"Order fulfilled: fulfilment_id={fulfilment_id}")
        finally:
            await conn.close()

    @activity.defn
    async def send_notification(self, order_id: str, notification_type: str) -> None:
        activity.logger.info(f"Sending notification: order={order_id} type={notification_type}")
        conn = await self._connect("role-write-notifications")
        try:
            notification_id = f"NOT-{uuid.uuid4().hex[:8].upper()}"
            await conn.execute(
                """
                INSERT INTO notifications (id, order_id, notification_type, status)
                VALUES ($1, $2, $3, 'SENT')
                """,
                notification_id,
                order_id,
                notification_type,
            )
            activity.logger.info(f"Notification sent: notification_id={notification_id}")
        finally:
            await conn.close()

    @activity.defn
    async def release_inventory(self, order_id: str, product_id: str, quantity: int) -> None:
        activity.logger.info(f"Releasing inventory: order={order_id} product={product_id} qty={quantity}")
        conn = await self._connect("role-write-inventory")
        try:
            await conn.execute(
                """
                UPDATE inventory SET quantity = quantity + $1, updated_at = NOW()
                WHERE product_id = $2
                """,
                quantity,
                product_id,
            )
            activity.logger.info(f"Inventory released: product={product_id} qty={quantity}")
        finally:
            await conn.close()
