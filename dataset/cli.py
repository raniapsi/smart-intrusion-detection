"""
Dataset generator CLI.

Step 2a usage:

    python -m dataset.cli generate-one-day \\
        --topology dataset/topology/building_b1_mini.yaml \\
        --user u001 \\
        --day 2026-04-01 \\
        --seed 42 \\
        --out dataset/output/sample_one_day.jsonl

Step 2b usage:

    python -m dataset.cli generate-baseline \\
        --topology dataset/topology/building_b1.yaml \\
        --start 2026-04-01 \\
        --days 30 \\
        --seed 42 \\
        --out dataset/output/train_normal_30d.jsonl

Both commands write a JSONL of UnifiedEvent objects (one per line) and
print a summary on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from dataset.generators import (
    Rng,
    generate_baseline,
    generate_user_day,
)
from dataset.topology import load_topology


def _cmd_generate_one_day(args: argparse.Namespace) -> int:
    topo = load_topology(args.topology)
    profile = topo.user_index().get(args.user)
    if profile is None:
        print(f"error: user '{args.user}' not in topology", file=sys.stderr)
        return 2

    try:
        day = date.fromisoformat(args.day)
    except ValueError:
        print(f"error: invalid --day '{args.day}', expected YYYY-MM-DD",
              file=sys.stderr)
        return 2

    rng_root = Rng(seed=args.seed)
    user_rng = rng_root.derive("user", profile.user_id)

    events = generate_user_day(
        profile=profile, topo=topo, day=day, rng=user_rng
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(ev.model_dump_json())
            f.write("\n")

    by_type: dict[str, int] = {}
    for ev in events:
        by_type[ev.event_type.value] = by_type.get(ev.event_type.value, 0) + 1
    print(
        f"generated {len(events)} events for {profile.user_id} on {day} "
        f"-> {out_path}",
        file=sys.stderr,
    )
    print(f"  breakdown: {json.dumps(by_type, sort_keys=True)}", file=sys.stderr)
    return 0


def _cmd_generate_baseline(args: argparse.Namespace) -> int:
    topo = load_topology(args.topology)

    try:
        start = date.fromisoformat(args.start)
    except ValueError:
        print(f"error: invalid --start '{args.start}', expected YYYY-MM-DD",
              file=sys.stderr)
        return 2

    if args.days <= 0:
        print("error: --days must be positive", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    type_counts: Counter[str] = Counter()
    n_total = 0

    print(
        f"generating baseline: {args.days} days from {start}, "
        f"{len(topo.users)} users, seed={args.seed}",
        file=sys.stderr,
    )

    with out_path.open("w", encoding="utf-8") as f:
        for ev in generate_baseline(
            topo=topo,
            start_day=start,
            n_days=args.days,
            seed=args.seed,
        ):
            f.write(ev.model_dump_json())
            f.write("\n")
            n_total += 1
            type_counts[ev.event_type.value] += 1
            if n_total % 10000 == 0:
                print(f"  ... {n_total} events written", file=sys.stderr)

    print(f"done: {n_total} events -> {out_path}", file=sys.stderr)
    print(
        f"  breakdown: {json.dumps(dict(sorted(type_counts.items())), sort_keys=True)}",
        file=sys.stderr,
    )
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  file size: {size_mb:.1f} MB", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dataset.cli",
        description="Generate synthetic event datasets for the AI engine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_one = sub.add_parser(
        "generate-one-day",
        help="Generate one user's events for one day (step 2a).",
    )
    p_one.add_argument("--topology", required=True,
                       help="Path to a topology YAML file")
    p_one.add_argument("--user", required=True, help="user_id, e.g. u001")
    p_one.add_argument("--day", required=True, help="YYYY-MM-DD")
    p_one.add_argument("--seed", type=int, default=42,
                       help="Master seed (default 42)")
    p_one.add_argument("--out", required=True, help="Output JSONL path")
    p_one.set_defaults(func=_cmd_generate_one_day)

    p_base = sub.add_parser(
        "generate-baseline",
        help="Generate a multi-day baseline dataset across all users (step 2b).",
    )
    p_base.add_argument("--topology", required=True,
                        help="Path to the full topology YAML")
    p_base.add_argument("--start", required=True,
                        help="First day, YYYY-MM-DD")
    p_base.add_argument("--days", type=int, required=True,
                        help="Number of calendar days to generate")
    p_base.add_argument("--seed", type=int, default=42,
                        help="Master seed (default 42)")
    p_base.add_argument("--out", required=True, help="Output JSONL path")
    p_base.set_defaults(func=_cmd_generate_baseline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
