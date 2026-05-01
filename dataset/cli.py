"""
Dataset generator CLI.

Step 2a:
    python -m dataset.cli generate-one-day \\
        --topology dataset/topology/building_b1_mini.yaml \\
        --user u001 --day 2026-04-01 --seed 42 \\
        --out dataset/output/sample_one_day.jsonl

Step 2b:
    python -m dataset.cli generate-baseline \\
        --topology dataset/topology/building_b1.yaml \\
        --start 2026-04-01 --days 30 --seed 42 \\
        --out dataset/output/train_normal_30d.jsonl

Step 2c:
    # One scenario:
    python -m dataset.cli generate-scenario \\
        --topology dataset/topology/building_b1.yaml \\
        --scenario forced_door \\
        --seed 42 \\
        --out-dir dataset/output

    # All seven scenarios at once:
    python -m dataset.cli generate-all-scenarios \\
        --topology dataset/topology/building_b1.yaml \\
        --seed 42 \\
        --out-dir dataset/output
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
    generate_day,
    generate_user_day,
)
from dataset.scenarios import REGISTRY
from dataset.topology import load_topology


# -----------------------------------------------------------------------------
# generate-one-day
# -----------------------------------------------------------------------------

def _cmd_generate_one_day(args: argparse.Namespace) -> int:
    topo = load_topology(args.topology)
    profile = topo.user_index().get(args.user)
    if profile is None:
        print(f"error: user '{args.user}' not in topology", file=sys.stderr)
        return 2
    try:
        day = date.fromisoformat(args.day)
    except ValueError:
        print(f"error: invalid --day '{args.day}'", file=sys.stderr)
        return 2

    rng_root = Rng(seed=args.seed)
    user_rng = rng_root.derive("user", profile.user_id)
    events = generate_user_day(profile=profile, topo=topo, day=day, rng=user_rng)

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


# -----------------------------------------------------------------------------
# generate-baseline
# -----------------------------------------------------------------------------

def _cmd_generate_baseline(args: argparse.Namespace) -> int:
    topo = load_topology(args.topology)
    try:
        start = date.fromisoformat(args.start)
    except ValueError:
        print(f"error: invalid --start '{args.start}'", file=sys.stderr)
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
            topo=topo, start_day=start, n_days=args.days, seed=args.seed,
        ):
            f.write(ev.model_dump_json())
            f.write("\n")
            n_total += 1
            type_counts[ev.event_type.value] += 1
            if n_total % 10000 == 0:
                print(f"  ... {n_total} events written", file=sys.stderr)

    print(f"done: {n_total} events -> {out_path}", file=sys.stderr)
    print(f"  breakdown: {json.dumps(dict(sorted(type_counts.items())))}",
          file=sys.stderr)
    print(f"  file size: {out_path.stat().st_size / (1024*1024):.1f} MB",
          file=sys.stderr)
    return 0


# -----------------------------------------------------------------------------
# generate-scenario / generate-all-scenarios
# -----------------------------------------------------------------------------

def _generate_one_scenario(
    *,
    scenario_name: str,
    topo,
    seed: int,
    out_dir: Path,
) -> int:
    """
    Run a single scenario: build a 1-day baseline, inject the attack,
    write the JSONL and the truth.json.
    Returns the number of events written, or -1 on error.
    """
    if scenario_name not in REGISTRY:
        print(
            f"error: unknown scenario '{scenario_name}'. Known: "
            f"{', '.join(sorted(REGISTRY.keys()))}",
            file=sys.stderr,
        )
        return -1

    scenario_cls = REGISTRY[scenario_name]
    scenario = scenario_cls()
    day = date.fromisoformat(scenario.default_day)

    # Build the baseline for that single day.
    rng = Rng(seed=seed)
    baseline_events = generate_day(topo=topo, day=day, rng=rng)

    # Inject the attack.
    inject_rng = rng.derive("scenario", scenario.name)
    result = scenario.inject(
        baseline=baseline_events, topo=topo, rng=inject_rng,
    )

    # Write outputs.
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"test_{scenario.name}.jsonl"
    truth_path = out_dir / f"test_{scenario.name}.truth.json"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for ev in result.events:
            f.write(ev.model_dump_json())
            f.write("\n")
    result.truth.write_json(truth_path)

    print(
        f"  {scenario.name}: {len(result.events)} events "
        f"({len(result.truth.attack_event_ids)} attack events) "
        f"on {day} -> {jsonl_path.name}, {truth_path.name}",
        file=sys.stderr,
    )
    return len(result.events)


def _cmd_generate_scenario(args: argparse.Namespace) -> int:
    topo = load_topology(args.topology)
    out_dir = Path(args.out_dir)
    n = _generate_one_scenario(
        scenario_name=args.scenario, topo=topo, seed=args.seed, out_dir=out_dir,
    )
    return 0 if n >= 0 else 2


def _cmd_generate_all_scenarios(args: argparse.Namespace) -> int:
    topo = load_topology(args.topology)
    out_dir = Path(args.out_dir)
    print(f"generating {len(REGISTRY)} scenarios into {out_dir}", file=sys.stderr)
    failed = 0
    for name in REGISTRY.keys():
        n = _generate_one_scenario(
            scenario_name=name, topo=topo, seed=args.seed, out_dir=out_dir,
        )
        if n < 0:
            failed += 1
    print(
        f"done: {len(REGISTRY) - failed}/{len(REGISTRY)} scenarios generated",
        file=sys.stderr,
    )
    return 0 if failed == 0 else 1


# -----------------------------------------------------------------------------
# Argument parser
# -----------------------------------------------------------------------------

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
    p_one.add_argument("--topology", required=True)
    p_one.add_argument("--user", required=True)
    p_one.add_argument("--day", required=True)
    p_one.add_argument("--seed", type=int, default=42)
    p_one.add_argument("--out", required=True)
    p_one.set_defaults(func=_cmd_generate_one_day)

    p_base = sub.add_parser(
        "generate-baseline",
        help="Generate a multi-day baseline dataset (step 2b).",
    )
    p_base.add_argument("--topology", required=True)
    p_base.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_base.add_argument("--days", type=int, required=True)
    p_base.add_argument("--seed", type=int, default=42)
    p_base.add_argument("--out", required=True)
    p_base.set_defaults(func=_cmd_generate_baseline)

    p_scn = sub.add_parser(
        "generate-scenario",
        help="Generate ONE attack scenario as a 1-day JSONL + truth.json (step 2c).",
    )
    p_scn.add_argument("--topology", required=True)
    p_scn.add_argument("--scenario", required=True,
                       choices=sorted(REGISTRY.keys()),
                       help="Scenario name")
    p_scn.add_argument("--seed", type=int, default=42)
    p_scn.add_argument("--out-dir", required=True,
                       help="Directory to write test_*.jsonl and test_*.truth.json")
    p_scn.set_defaults(func=_cmd_generate_scenario)

    p_all = sub.add_parser(
        "generate-all-scenarios",
        help="Generate all 7 attack scenarios (step 2c).",
    )
    p_all.add_argument("--topology", required=True)
    p_all.add_argument("--seed", type=int, default=42)
    p_all.add_argument("--out-dir", required=True)
    p_all.set_defaults(func=_cmd_generate_all_scenarios)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())