"""
Features CLI.

Two commands:

1. learn-baselines: scan a JSONL of normal events, compute per-device
   network baselines, persist to JSON.

   python -m features.cli learn-baselines \\
       --events dataset/output/train_normal_30d.jsonl \\
       --out features/output/baselines.json

2. extract: produce a feature DataFrame for a JSONL of events.
   The output is a Parquet file (compact, fast to reload in step 4).

   python -m features.cli extract \\
       --events dataset/output/test_forced_door.jsonl \\
       --topology dataset/topology/building_b1.yaml \\
       --baselines features/output/baselines.json \\
       --out features/output/test_forced_door.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dataset.topology import load_topology
from features import (
    BaselineCatalog,
    FeatureExtractor,
    learn_baselines,
    read_events_jsonl,
)


def _cmd_learn_baselines(args: argparse.Namespace) -> int:
    events_path = Path(args.events)
    if not events_path.is_file():
        print(f"error: events file not found: {events_path}", file=sys.stderr)
        return 2
    out_path = Path(args.out)

    print(f"learning baselines from {events_path} ...", file=sys.stderr)
    catalog = learn_baselines(read_events_jsonl(events_path))

    n_dev = len(catalog.per_device)
    n_trusted = sum(1 for b in catalog.per_device.values() if b.is_trusted())
    print(
        f"  observed {n_dev} devices "
        f"({n_trusted} with >= MIN_OBSERVATIONS samples)",
        file=sys.stderr,
    )
    print(
        f"  global: n={catalog.global_baseline.n_observations} "
        f"bytes_out_mean={catalog.global_baseline.bytes_out_mean:.0f} "
        f"std={catalog.global_baseline.bytes_out_std:.0f}",
        file=sys.stderr,
    )

    catalog.write_json(out_path)
    print(f"wrote {out_path}", file=sys.stderr)
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    events_path = Path(args.events)
    topo_path = Path(args.topology)
    baselines_path = Path(args.baselines)
    out_path = Path(args.out)

    if not events_path.is_file():
        print(f"error: events file not found: {events_path}", file=sys.stderr)
        return 2
    if not topo_path.is_file():
        print(f"error: topology file not found: {topo_path}", file=sys.stderr)
        return 2
    if not baselines_path.is_file():
        print(
            f"error: baselines file not found: {baselines_path}\n"
            "  run `learn-baselines` first.",
            file=sys.stderr,
        )
        return 2

    topo = load_topology(topo_path)
    catalog = BaselineCatalog.read_json(baselines_path)
    extractor = FeatureExtractor(topology=topo, baselines=catalog)

    print(f"extracting features from {events_path} ...", file=sys.stderr)
    df = extractor.extract_dataframe(read_events_jsonl(events_path))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix == ".parquet":
        df.to_parquet(out_path, index=False)
    elif out_path.suffix == ".csv":
        df.to_csv(out_path, index=False)
    else:
        print(
            f"warning: unknown extension {out_path.suffix}, writing as parquet",
            file=sys.stderr,
        )
        df.to_parquet(out_path, index=False)

    print(
        f"  {len(df)} rows × {len(df.columns)} cols -> {out_path} "
        f"({out_path.stat().st_size / (1024*1024):.1f} MB)",
        file=sys.stderr,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="features.cli",
        description="Feature engineering for the AI engine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_learn = sub.add_parser(
        "learn-baselines",
        help="Learn per-device network baselines from a normal dataset.",
    )
    p_learn.add_argument("--events", required=True,
                         help="Path to normal events JSONL")
    p_learn.add_argument("--out", required=True,
                         help="Output baselines JSON")
    p_learn.set_defaults(func=_cmd_learn_baselines)

    p_ext = sub.add_parser(
        "extract",
        help="Extract a feature DataFrame from an events JSONL.",
    )
    p_ext.add_argument("--events", required=True,
                       help="Path to events JSONL")
    p_ext.add_argument("--topology", required=True,
                       help="Path to topology YAML")
    p_ext.add_argument("--baselines", required=True,
                       help="Path to baselines.json (from learn-baselines)")
    p_ext.add_argument("--out", required=True,
                       help="Output Parquet (or .csv) path")
    p_ext.set_defaults(func=_cmd_extract)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())