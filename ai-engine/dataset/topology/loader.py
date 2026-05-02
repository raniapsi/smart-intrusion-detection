"""
Load a building topology from a YAML file into a validated BuildingTopology.

Pydantic does the heavy lifting: any malformed YAML (missing fields,
wrong enum values, duplicate IDs) is caught here, before any generator
runs. This is the only entry point for getting a topology object.
"""

from pathlib import Path
from typing import Union

import yaml

from schemas import BuildingTopology


def load_topology(path: Union[str, Path]) -> BuildingTopology:
    """
    Load and validate a building topology from a YAML file.

    Args:
        path: filesystem path to the YAML file.

    Returns:
        A fully validated BuildingTopology instance.

    Raises:
        FileNotFoundError: if the file does not exist.
        pydantic.ValidationError: if the YAML content does not conform
            to the BuildingTopology schema.
        yaml.YAMLError: if the file is not valid YAML.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Topology file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    # Pydantic does the rest: enum coercion, time parsing, uniqueness checks.
    return BuildingTopology.model_validate(raw)
