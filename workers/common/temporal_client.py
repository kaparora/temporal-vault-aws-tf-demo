from temporalio.client import Client, TLSConfig


async def connect_temporal_client(
    temporal_address: str,
    temporal_namespace: str,
    tls_cert_path: str,
    tls_key_path: str,
) -> Client:
    with open(tls_cert_path, "rb") as f:
        client_cert = f.read()
    with open(tls_key_path, "rb") as f:
        client_key = f.read()

    return await Client.connect(
        temporal_address,
        namespace=temporal_namespace,
        tls=TLSConfig(
            client_cert=client_cert,
            client_private_key=client_key,
        ),
    )
