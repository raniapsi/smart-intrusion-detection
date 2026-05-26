"""
Fusion CLI.

One command:

    python3 -m fusion.cli fuse \\
        --scored models/output/test_forced_door.scored.parquet \\
        --out fusion/output/test_forced_door.fused.parquet

Reads a scored parquet (output of `models.cli score`), runs the
correlator + fusion scorer, and writes the same DataFrame with four new
columns appended:
    - score_combined
    - score_correlation_peer
    - score_final
    - ai_classification

Also has a `fuse-all` command that processes a whole directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from fusion import (
    DEFAULT_CORRELATION_WEIGHT,
    DEFAULT_MIN_PEER_SCORE,
    DEFAULT_WINDOW_SECONDS,
    fuse_scores,
)


def _fuse_one(
    scored_path: Path,
    out_path: Path,
    *,
    correlation_weight: float,
    window_seconds: float,
    min_peer: float,
) -> int:
    if not scored_path.is_file():
        print(f"error: scored file not found: {scored_path}", file=sys.stderr)
        return 2

    df = pd.read_parquet(scored_path)
    fused = fuse_scores(
        df,
        correlation_weight=correlation_weight,
        correlation_window_seconds=window_seconds,
        correlation_min_peer=min_peer,
    )
    out = pd.concat([df, fused], axis=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)

    n = len(out)
    n_correlated = int((out["score_correlation_peer"] > 0).sum())
    n_critical = int((out["ai_classification"] == "CRITICAL").sum())
    n_suspect = int((out["ai_classification"] == "SUSPECT").sum())
    print(
        f"  fused {n} events -> {out_path}  "
        f"({n_correlated} correlated, {n_critical} CRITICAL, "
        f"{n_suspect} SUSPECT)",
        file=sys.stderr,
    )
    return 0


def _cmd_fuse(args: argparse.Namespace) -> int:
    return _fuse_one(
        Path(args.scored), Path(args.out),
        correlation_weight=args.correlation_weight,
        window_seconds=args.window_seconds,
        min_peer=args.min_peer,
    )


def _cmd_fuse_all(args: argparse.Namespace) -> int:
    scored_dir = Path(args.scored_dir)
    out_dir = Path(args.out_dir)
    if not scored_dir.is_dir():
        print(f"error: scored_dir not found: {scored_dir}", file=sys.stderr)
        return 2

    scored_files = sorted(scored_dir.glob("*.scored.parquet"))
    if not scored_files:
        print(f"no *.scored.parquet files in {scored_dir}", file=sys.stderr)
        return 1

    print(f"fusing {len(scored_files)} files into {out_dir}", file=sys.stderr)
    failed = 0
    for sp in scored_files:
        # rename: test_X.scored.parquet -> test_X.fused.parquet
        out_name = sp.name.replace(".scored.parquet", ".fused.parquet")
        rc = _fuse_one(
            sp, out_dir / out_name,
            correlation_weight=args.correlation_weight,
            window_seconds=args.window_seconds,
            min_peer=args.min_peer,
        )
        if rc != 0:
            failed += 1
    print(
        f"done: {len(scored_files) - failed}/{len(scored_files)} files fused",
        file=sys.stderr,
    )
    return 0 if failed == 0 else 1


def _cmd_evaluate_all(args: argparse.Namespace) -> int:
    """
    Evaluate fused parquets using `score_final`. Reuses the evaluation
    machinery from the `evaluation` package.
    """
    from dataclasses import asdict
    from evaluation import evaluate_thresholds, load_truth

    fused_dir = Path(args.fused_dir)
    truth_dir = Path(args.truth_dir)
    if not fused_dir.is_dir():
        print(f"error: fused_dir not found: {fused_dir}", file=sys.stderr)
        return 2
    if not truth_dir.is_dir():
        print(f"error: truth_dir not found: {truth_dir}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for truth_path in sorted(truth_dir.glob("test_*.truth.json")):
        scenario = truth_path.stem.replace(".truth", "").replace("test_", "")
        fused_path = fused_dir / f"test_{scenario}.fused.parquet"
        if not fused_path.is_file():
            print(
                f"  skipping {scenario} — no fused parquet at {fused_path}",
                file=sys.stderr,
            )
            continue
        df = pd.read_parquet(fused_path)
        truth = load_truth(truth_path)
        # Evaluate score_final at the standard thresholds.
        for m in evaluate_thresholds(
            df_features=df, score_column="score_final",
            truth=truth, thresholds=(0.3, 0.5, 0.7),
        ):
            rows.append(asdict(m))
        # Also evaluate score_combined (max of rules+if without correlation)
        # for comparison.
        for m in evaluate_thresholds(
            df_features=df, score_column="score_combined",
            truth=truth, thresholds=(0.3, 0.5, 0.7),
        ):
            rows.append(asdict(m))

    if not rows:
        print("no scenarios evaluated", file=sys.stderr)
        return 1

    df_all = pd.DataFrame(rows)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_all.to_csv(out_path, index=False)

    print("\n=== Fusion Summary ===")
    summary = df_all.groupby(["scenario", "score_column"]).agg(
        best_f1=("f1", "max"),
        max_attack=("max_attack_score", "max"),
        scenario_detected=("scenario_detected", "any"),
    ).reset_index()
    print(summary.to_string(index=False))
    print(f"\nfull metrics -> {out_path}", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fusion.cli",
        description="Fuse rules + IF scores with cross-layer correlation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common_args: list[tuple[tuple, dict]] = [
        (("--correlation-weight",),
         {"type": float, "default": DEFAULT_CORRELATION_WEIGHT,
          "help": "Weight applied to correlation bonus (default 0.30)"}),
        (("--window-seconds",),
         {"type": float, "default": DEFAULT_WINDOW_SECONDS,
          "help": "Correlation time window (default 60s)"}),
        (("--min-peer",),
         {"type": float, "default": DEFAULT_MIN_PEER_SCORE,
          "help": "Min peer score to count (default 0.30)"}),
    ]

    p = sub.add_parser("fuse", help="Fuse one scored file.")
    p.add_argument("--scored", required=True)
    p.add_argument("--out", required=True)
    for a, kw in common_args:
        p.add_argument(*a, **kw)
    p.set_defaults(func=_cmd_fuse)

    p_all = sub.add_parser(
        "fuse-all", help="Fuse all *.scored.parquet in a directory.",
    )
    p_all.add_argument("--scored-dir", required=True)
    p_all.add_argument("--out-dir", required=True)
    for a, kw in common_args:
        p_all.add_argument(*a, **kw)
    p_all.set_defaults(func=_cmd_fuse_all)

    p_eval = sub.add_parser(
        "evaluate-all",
        help="Evaluate all fused parquets against the truth files.",
    )
    p_eval.add_argument("--fused-dir", required=True)
    p_eval.add_argument("--truth-dir", required=True)
    p_eval.add_argument("--out", required=True)
    p_eval.set_defaults(func=_cmd_evaluate_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())