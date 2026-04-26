import os
from pathlib import Path


def read_secret(env_var: str, is_file: bool = False) -> str:
    """
    Read a secret from environment variable.
    If is_file=True, treat the env var value as a file path and read its contents.
    Otherwise, return the env var value directly.
    """
    value = os.environ[env_var]

    if is_file and value.startswith(("/", ".")):
        # Looks like a file path, read it
        secret_path = Path(value)
        if secret_path.exists():
            return secret_path.read_text().strip()
        else:
            raise FileNotFoundError(f"Secret file not found: {secret_path}")

    return value
