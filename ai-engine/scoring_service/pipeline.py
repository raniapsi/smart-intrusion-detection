"""
Scoring pipeline.

Composes feature extraction + IF scoring + rules + fusion into a single
callable. Used by both the batch driver (this package's `batch` module)
and the streaming driver (`stream` module).

The pipeline holds the LOADED model and baselines in memory and is
designed to be called many times — at module init you pay the cost of
loading the joblib + JSON, then every batch / event is fast.

Single-shot batch interface:
    pipeline = ScoringPipeline.from_paths(
        topology_path="dataset/topology/building_b1.yaml",
        baselines_path="features/output/baselines.json",
        model_path="models/trained/isoforest.joblib",
    )
    enriched_events, alerts = pipeline.run_batch(events)

Streaming interface (skeleton, exercised in stream.py):
    pipeline.process_event(event) -> (EnrichedEvent, Optional[Alert])
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from dataset.topology import load_topology
from features import BaselineCatalog, FeatureExtractor
from fusion import fuse_scores
from models import TrainedIsolationForest, score_rules
from schemas import (
    AIClassification,
    Alert,
    BuildingTopology,
    EnrichedEvent,
    UnifiedEvent,
)

from .alert_builder import build_alert_from_enriched


@dataclass
class PipelineComponents:
    """The loaded heavy artefacts the pipeline needs."""

    topology: BuildingTopology
    baselines: BaselineCatalog
    model: TrainedIsolationForest


class ScoringPipeline:
    """
    End-to-end pipeline: UnifiedEvent[] -> (EnrichedEvent[], Alert[]).

    Stateful (the feature extractor maintains sliding windows), but
    `run_batch` resets the state between calls. For streaming use,
    create one pipeline instance and reuse it across `process_event`
    calls — the state is then meaningful.
    """

    def __init__(self, components: PipelineComponents) -> None:
        self._components = components
        self._extractor = FeatureExtractor(
            topology=components.topology,
            baselines=components.baselines,
        )

    # -------------------------------------------------------------------------
    # Construction helpers
    # -------------------------------------------------------------------------

    @classmethod
    def from_paths(
        cls,
        *,
        topology_path: str | Path,
        baselines_path: str | Path,
        model_path: str | Path,
    ) -> "ScoringPipeline":
        topo = load_topology(Path(topology_path))
        catalog = BaselineCatalog.read_json(Path(baselines_path))
        model = TrainedIsolationForest.load(Path(model_path))
        return cls(PipelineComponents(
            topology=topo,
            baselines=catalog,
            model=model,
        ))

    # -------------------------------------------------------------------------
    # Batch mode
    # -------------------------------------------------------------------------

    def run_batch(
        self, events: Iterable[UnifiedEvent]
    ) -> tuple[list[EnrichedEvent], list[Alert]]:
        """
        Process a finite collection of events in one shot.

        Steps:
          1. Materialise events into a list (we need to traverse twice:
             once for feature extraction, once to assemble EnrichedEvents).
          2. Extract features into a DataFrame.
          3. Score with rules + IF.
          4. Fuse + classify.
          5. Build EnrichedEvent for every event, Alert for every
             non-NORMAL classification.

        Returns: (enriched_events, alerts) — both lists, both in the
        original event order.
        """
        events_list = list(events)
        if not events_list:
            return [], []

        # Reset the extractor's sliding state so a new batch is independent
        # of any previous run.
        self._extractor.reset()

        # 1) Feature extraction
        df_features = self._extractor.extract_dataframe(events_list)

        # 2) Score IF + rules
        score_if = self._components.model.score(df_features)
        rules_df = score_rules(df_features)
        df = df_features.copy()
        df["score_if"] = score_if
        df["score_rules"] = rules_df["score_rules"].to_numpy()
        df["rule_hits"] = rules_df["rule_hits"].to_numpy()

        # 3) Fuse + classify
        fused = fuse_scores(df)
        df["score_combined"] = fused["score_combined"].to_numpy()
        df["score_correlation_peer"] = fused["score_correlation_peer"].to_numpy()
        df["score_final"] = fused["score_final"].to_numpy()
        df["ai_classification"] = fused["ai_classification"].to_numpy()

        # 4) Assemble enriched events + alerts
        enriched_events: list[EnrichedEvent] = []
        alerts: list[Alert] = []

        # df is in the same order as events_list (the extractor preserves it).
        for ev, (_, row) in zip(events_list, df.iterrows()):
            enriched = _enrich(ev, row)
            enriched_events.append(enriched)

            if enriched.ai_classification != AIClassification.NORMAL:
                alert = build_alert_from_enriched(
                    enriched=enriched,
                    rule_hits=str(row.get("rule_hits", "")) or None,
                    score_if=float(row["score_if"]),
                    score_rules=float(row["score_rules"]),
                    correlation_peer=float(row["score_correlation_peer"]),
                )
                alerts.append(alert)

        return enriched_events, alerts

    # -------------------------------------------------------------------------
    # Streaming mode (skeleton)
    # -------------------------------------------------------------------------

    def process_event(
        self, event: UnifiedEvent
    ) -> tuple[EnrichedEvent, Optional[Alert]]:
        """
        Process a single event in streaming mode.

        Returns the enriched event and, if its classification is non-NORMAL,
        an Alert object. The internal sliding-window state is updated.

        Note: the cross-layer correlator NEEDS a window of upcoming events
        to look forward in time. In a true streaming setting we cannot do
        this without buffering. For now this method runs the pipeline on
        a 1-event "batch" and returns a forward-looking score of 0 for
        correlation. The full streaming implementation in stream.py will
        add a small ring buffer to look back, which is sufficient for the
        physical-cyber correlation case (cyber typically lags physical).
        """
        # Single-event batch: easiest correct implementation, suitable
        # while we wait for the streaming infrastructure.
        enriched, alerts = self.run_batch([event])
        return enriched[0], (alerts[0] if alerts else None)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _enrich(event: UnifiedEvent, row: pd.Series) -> EnrichedEvent:
    """
    Promote a UnifiedEvent to an EnrichedEvent by attaching the AI fields.
    """
    score = float(row["score_final"])
    classification = AIClassification(str(row["ai_classification"]))

    # Pydantic v2: use model_dump to get a dict, then construct EnrichedEvent.
    # We avoid validation overhead by passing through model_construct, but
    # validation is cheap enough at this scale and catches bugs.
    payload = event.model_dump()
    payload["ai_score"] = score
    payload["ai_classification"] = classification
    return EnrichedEvent(**payload)