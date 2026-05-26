"""
Backend launcher.

Usage:

    python3 -m backend.cli serve \\
        --topology dataset/topology/building_b1.yaml \\
        --enriched scoring_service/output/test_hybrid_intrusion.enriched.jsonl \\
        --alerts scoring_service/output/test_hybrid_intrusion.alerts.jsonl \\
        --port 8000

Multi-file is allowed:
    --enriched a.jsonl --enriched b.jsonl --alerts a-alerts.jsonl --alerts b-alerts.jsonl

Defaults pull all *.enriched.jsonl and *.alerts.jsonl in a directory:

    python3 -m backend.cli serve \\
        --topology dataset/topology/building_b1.yaml \\
        --data-dir scoring_service/output \\
        --port 8000
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from backend.app import BackendConfig, create_app
from backend.replay import DEFAULT_SPEED_FACTOR


def _gather_data_dir(data_dir: Path) -> tuple[list[Path], list[Path]]:
    enriched = sorted(data_dir.glob("*.enriched.jsonl"))
    alerts = sorted(data_dir.glob("*.alerts.jsonl"))
    return enriched, alerts


def _cmd_serve(args: argparse.Namespace) -> int:
    topo_path = Path(args.topology)
    if not topo_path.is_file():
        print(f"error: topology not found: {topo_path}", file=sys.stderr)
        return 2

    enriched: list[Path] = list(map(Path, args.enriched or []))
    alerts: list[Path] = list(map(Path, args.alerts or []))

    if args.data_dir:
        d = Path(args.data_dir)
        if not d.is_dir():
            print(f"error: data_dir not found: {d}", file=sys.stderr)
            return 2
        a, b = _gather_data_dir(d)
        enriched.extend(a)
        alerts.extend(b)

    if not enriched:
        print(
            "warning: no enriched files specified — backend will start "
            "with an empty datastore.",
            file=sys.stderr,
        )

    baselines_path = Path(args.baselines) if args.baselines else None
    model_path = Path(args.model) if args.model else None
    if (baselines_path is None) != (model_path is None):
        print(
            "error: --baselines and --model must be provided together "
            "for live ingestion",
            file=sys.stderr,
        )
        return 2
    for label, path in (("baselines", baselines_path), ("model", model_path)):
        if path is not None and not path.is_file():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2

    config = BackendConfig(
        topology_path=topo_path,
        enriched_paths=enriched,
        alerts_paths=alerts,
        replay_speed_factor=args.speed,
        enable_replay=not args.no_replay,
        cors_origins=args.cors_origins or ["*"],
        baselines_path=baselines_path,
        model_path=model_path,
        kafka_brokers=args.kafka_brokers,
        kafka_topic_raw=args.kafka_topic_raw,
        kafka_topic_enriched=args.kafka_topic_enriched,
        kafka_topic_alerts=args.kafka_topic_alerts,
        kafka_consumer_group=args.kafka_consumer_group,
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = create_app(config)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backend.cli",
        description="SOC backend HTTP+WebSocket server.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="Start the FastAPI server.")
    p.add_argument("--topology", required=True, help="Topology YAML path")
    p.add_argument(
        "--enriched", action="append",
        help="Path to one enriched JSONL (repeatable)",
    )
    p.add_argument(
        "--alerts", action="append",
        help="Path to one alerts JSONL (repeatable)",
    )
    p.add_argument(
        "--data-dir",
        help="Directory: load all *.enriched.jsonl and *.alerts.jsonl",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument(
        "--speed", type=float, default=DEFAULT_SPEED_FACTOR,
        help="Replay speed factor (1 sec wall = N sec sim)",
    )
    p.add_argument(
        "--no-replay", action="store_true",
        help="Disable temporal replay (WebSocket stays silent)",
    )
    p.add_argument(
        "--cors-origins", action="append",
        help="Allowed CORS origin (repeatable). Defaults to '*'.",
    )
    p.add_argument(
        "--baselines",
        help="Baselines JSON path; required with --model for live ingestion",
    )
    p.add_argument(
        "--model",
        help="Trained Isolation Forest joblib path; required with --baselines",
    )
    p.add_argument(
        "--kafka-brokers",
        help="Kafka bootstrap servers. Enables the background Kafka consumer.",
    )
    p.add_argument(
        "--kafka-topic-raw",
        default="events.raw",
        help="Kafka topic consumed by the AI engine.",
    )
    p.add_argument(
        "--kafka-topic-enriched",
        default="events.enriched",
        help="Kafka topic where enriched events are published.",
    )
    p.add_argument(
        "--kafka-topic-alerts",
        default="alerts.critical",
        help="Kafka topic where generated alerts are published.",
    )
    p.add_argument(
        "--kafka-consumer-group",
        default="ai-engine-scoring",
        help="Kafka consumer group for the AI engine.",
    )
    p.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
