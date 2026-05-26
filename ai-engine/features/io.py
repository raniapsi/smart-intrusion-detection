"""
JSONL I/O for events.

One small helper. Lives in `features/` because it's the package that
needs to *read* raw events back from disk (the dataset package only
*writes* them).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from schemas import UnifiedEvent


def read_events_jsonl(path: Path) -> Iterator[UnifiedEvent]:
    """
    Stream events from a JSONL file. Validates each line against the
    UnifiedEvent schema; lines that fail validation raise the underlying
    pydantic ValidationError immediately (we'd rather fail loudly than
    silently skip bad data).
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield UnifiedEvent.model_validate_json(line)