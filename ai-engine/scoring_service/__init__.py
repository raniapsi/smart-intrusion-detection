"""
ai-engine scoring service.

End-to-end pipeline: UnifiedEvent -> EnrichedEvent + Alert.
"""

from .alert_builder import build_alert_from_enriched
from .batch import run_batch_jsonl
from .pipeline import PipelineComponents, ScoringPipeline
from .stream import StreamConfig, StreamRunner

__all__ = [
    "ScoringPipeline",
    "PipelineComponents",
    "run_batch_jsonl",
    "build_alert_from_enriched",
    "StreamRunner",
    "StreamConfig",
]