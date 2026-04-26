import json
import os
import subprocess
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


def run_terraform(
    module_dir: str,
    variables: dict[str, str],
    subcommand: str = "apply",
) -> dict[str, Any] | None:
    """
    Runs terraform init + apply/destroy on a module directory.
    For apply: returns parsed outputs.
    For destroy: returns None.
    Variables are injected as TF_VAR_* environment variables — never as CLI args
    so sensitive values don't appear in process listings.
    """
    module_path = Path(module_dir).resolve()
    env = {**os.environ}
    for key, value in variables.items():
        env[f"TF_VAR_{key}"] = str(value)

    logger.info("terraform_init", module=str(module_path))
    subprocess.run(
        ["terraform", "init", "-no-color"],
        cwd=module_path,
        env=env,
        check=True,
    )

    logger.info(f"terraform_{subcommand}", module=str(module_path))
    subprocess.run(
        ["terraform", subcommand, "-auto-approve", "-no-color"],
        cwd=module_path,
        env=env,
        check=True,
    )

    if subcommand == "destroy":
        return None

    logger.info("terraform_output", module=str(module_path))
    result = subprocess.run(
        ["terraform", "output", "-json", "-no-color"],
        cwd=module_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    # Terraform output JSON: {"key": {"value": ..., "type": ..., "sensitive": bool}}
    raw = json.loads(result.stdout)
    return {key: meta["value"] for key, meta in raw.items()}
