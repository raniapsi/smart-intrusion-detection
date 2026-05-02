"""
Scoring service CLI.

Two commands:

1. score-batch: run the pipeline on a JSONL of UnifiedEvents and write
   enriched.jsonl + alerts.jsonl.

   python3 -m scoring_service.cli score-batch \\
       --events dataset/output/test_forced_door.jsonl \\
       --topology dataset/topology/building_b1.yaml \\
       --baselines features/output/baselines.json \\
       --model models/trained/isoforest.joblib \\
       --enriched-out scoring_service/output/test_forced_door.enriched.jsonl \\
       --alerts-out scoring_service/output/test_forced_door.alerts.jsonl

2. score-batch-all: same but for every test_*.jsonl in a directory.

   python3 -m scoring_service.cli score-batch-all \\
       --events-dir dataset/output \\
       --topology dataset/topology/building_b1.yaml \\
       --baselines features/output/baselines.json \\
       --model models/trained/isoforest.joblib \\
       --out-dir scoring_service/output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scoring_service.batch import run_batch_jsonl
from scoring_service.pipeline import ScoringPipeline


def _build_pipeline(args: argparse.Namespace) -> ScoringPipeline:
    return ScoringPipeline.from_paths(
        topology_path=args.topology,
        baselines_path=args.baselines,
        model_path=args.model,
    )


def _cmd_score_batch(args: argparse.Namespace) -> int:
    events_path = Path(args.events)
    if not events_path.is_file():
        print(f"error: events file not found: {events_path}", file=sys.stderr)
        return 2

    pipeline = _build_pipeline(args)
    n_enriched, n_alerts = run_batch_jsonl(
        pipeline=pipeline,
        events_path=events_path,
        enriched_out=Path(args.enriched_out),
        alerts_out=Path(args.alerts_out),
    )
    print(
        f"  {events_path.name}: {n_enriched} enriched, {n_alerts} alerts",
        file=sys.stderr,
    )
    return 0


def _cmd_score_batch_all(args: argparse.Namespace) -> int:
    events_dir = Path(args.events_dir)
    out_dir = Path(args.out_dir)
    if not events_dir.is_dir():
        print(f"error: events_dir not found: {events_dir}", file=sys.stderr)
        return 2

    # Process every test_*.jsonl in the directory.
    files = sorted(events_dir.glob("test_*.jsonl"))
    if not files:
        print(f"no test_*.jsonl files found in {events_dir}", file=sys.stderr)
        return 1

    print(f"loading pipeline ...", file=sys.stderr)
    pipeline = _build_pipeline(args)

    print(f"scoring {len(files)} files into {out_dir}", file=sys.stderr)
    failed = 0
    for ev_path in files:
        # Output filenames: keep the test_<name> stem.
        stem = ev_path.stem  # e.g. "test_forced_door"
        try:
            n_enriched, n_alerts = run_batch_jsonl(
                pipeline=pipeline,
                events_path=ev_path,
                enriched_out=out_dir / f"{stem}.enriched.jsonl",
                alerts_out=out_dir / f"{stem}.alerts.jsonl",
            )
            print(
                f"  {stem}: {n_enriched} enriched, {n_alerts} alerts",
                file=sys.stderr,
            )
        except Exception as e:  # noqa: BLE001 — keep going on per-file error
            print(f"  {stem}: ERROR {e}", file=sys.stderr)
            failed += 1

    print(
        f"done: {len(files) - failed}/{len(files)} files scored",
        file=sys.stderr,
    )
    return 0 if failed == 0 else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scoring_service.cli",
        description="End-to-end scoring (features + IF + rules + fusion).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common: list[tuple[tuple, dict]] = [
        (("--topology",),  {"required": True}),
        (("--baselines",), {"required": True}),
        (("--model",),     {"required": True}),
    ]

    p = sub.add_parser("score-batch", help="Score one events JSONL file.")
    p.add_argument("--events", required=True)
    p.add_argument("--enriched-out", required=True)
    p.add_argument("--alerts-out", required=True)
    for a, kw in common:
        p.add_argument(*a, **kw)
    p.set_defaults(func=_cmd_score_batch)

    p_all = sub.add_parser(
        "score-batch-all",
        help="Score every test_*.jsonl in a directory.",
    )
    p_all.add_argument("--events-dir", required=True)
    p_all.add_argument("--out-dir", required=True)
    for a, kw in common:
        p_all.add_argument(*a, **kw)
    p_all.set_defaults(func=_cmd_score_batch_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())