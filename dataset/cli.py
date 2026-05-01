"""
Dataset generator CLI.

Step 2a usage:

    python -m dataset.cli generate-one-day \\
        --topology dataset/topology/building_b1_mini.yaml \\
        --user u001 \\
        --day 2026-04-01 \\
        --seed 42 \\
        --out dataset/output/sample_one_day.jsonl

Produces a JSONL file (one UnifiedEvent per line) and prints a short
summary on stderr.

Step 2b will add a `generate-baseline` command that runs all users for N days.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dataset.generators import Rng, generate_user_day
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
            # model_dump_json() respects the schema (UTC datetimes, UUIDs as strings).
            f.write(ev.model_dump_json())
            f.write("\n")

    # Quick summary on stderr (so stdout stays clean for piping).
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
