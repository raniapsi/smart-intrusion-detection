"""
Batch driver: JSONL events in, JSONL enriched events + JSONL alerts out.

This is the most useful interface for the project today: it lets us
re-score recorded JSONL files (the dataset's baseline + scenarios)
without needing any streaming infrastructure.

Expected file layout per the README:
  - input:  events.jsonl   (UnifiedEvent, one per line)
  - output: enriched.jsonl (EnrichedEvent, one per line)
  - output: alerts.jsonl   (Alert, one per line — only non-NORMAL events)
"""

from __future__ import annotations

from pathlib import Path

from features import read_events_jsonl

from .pipeline import ScoringPipeline


def run_batch_jsonl(
    *,
    pipeline: ScoringPipeline,
    events_path: Path,
    enriched_out: Path,
    alerts_out: Path,
) -> tuple[int, int]:
    """
    Run the pipeline on a JSONL of UnifiedEvents.

    Args:
        pipeline: a ready-to-use ScoringPipeline.
        events_path: input JSONL of UnifiedEvent.
        enriched_out: output JSONL of EnrichedEvent (one per input event).
        alerts_out: output JSONL of Alert (only non-NORMAL events).

    Returns: (n_enriched, n_alerts) for caller-side reporting.
    """
    events_path = Path(events_path)
    enriched_out = Path(enriched_out)
    alerts_out = Path(alerts_out)

    events = list(read_events_jsonl(events_path))
    enriched_events, alerts = pipeline.run_batch(events)

    enriched_out.parent.mkdir(parents=True, exist_ok=True)
    with enriched_out.open("w", encoding="utf-8") as f:
        for ev in enriched_events:
            f.write(ev.model_dump_json())
            f.write("\n")

    alerts_out.parent.mkdir(parents=True, exist_ok=True)
    with alerts_out.open("w", encoding="utf-8") as f:
        for al in alerts:
            f.write(al.model_dump_json())
            f.write("\n")

    return len(enriched_events), len(alerts)