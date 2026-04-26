import hvac
import structlog
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

logger = structlog.get_logger()


class VaultTokenRefreshInterceptor(Interceptor):
    def __init__(self, vault_client: hvac.Client):
        self.vault_client = vault_client

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _VaultRefreshInbound(next, self.vault_client)


class _VaultRefreshInbound(ActivityInboundInterceptor):
    def __init__(self, next: ActivityInboundInterceptor, vault_client: hvac.Client):
        super().__init__(next)
        self.vault_client = vault_client

    async def execute_activity(self, input: ExecuteActivityInput):
        try:
            token_info = self.vault_client.auth.token.lookup_self()
            ttl = token_info["data"].get("ttl", 999)
            if ttl < 600:
                self.vault_client.auth.token.renew_self(increment="1h")
                logger.info("vault_token_renewed", remaining_ttl_seconds=ttl)
        except Exception as exc:
            logger.warning("vault_token_refresh_failed", error=str(exc))
        return await self.next.execute_activity(input)
