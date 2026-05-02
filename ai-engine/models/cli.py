"""
Models CLI.

Three commands:

1. train: fit an Isolation Forest on a feature parquet and persist it.

   python -m models.cli train \\
       --features features/output/train_features.parquet \\
       --out models/trained/isoforest.joblib

2. score: load a trained IF + run rules on a feature parquet, write a
   parquet with new columns: score_if, score_rules, rule_hits.

   python -m models.cli score \\
       --features features/output/test_forced_door.parquet \\
       --model models/trained/isoforest.joblib \\
       --out models/output/test_forced_door.scored.parquet

3. evaluate: compare scored features against a truth.json. Prints a
   compact summary and writes a metrics CSV.

   python -m models.cli evaluate \\
       --scored models/output/test_forced_door.scored.parquet \\
       --truth dataset/output/test_forced_door.truth.json
   
   python -m models.cli evaluate-all \\
       --scored-dir models/output \\
       --truth-dir dataset/output \\
       --out models/output/eval_summary.csv

for sc in badge_off_hours forced_door tailgating revoked_badge \
          hybrid_intrusion camera_compromise credential_theft; do
    python -m features.cli extract \
        --events dataset/output/test_${sc}.jsonl \
        --topology dataset/topology/building_b1.yaml \
        --baselines features/output/baselines.json \
        --out features/output/test_${sc}.parquet
    python -m models.cli score \
        --features features/output/test_${sc}.parquet \
        --model models/trained/isoforest.joblib \
        --out models/output/test_${sc}.scored.parquet
done
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from evaluation import evaluate_thresholds, load_truth, metrics_to_dataframe
from models import TrainedIsolationForest, score_rules, train_isolation_forest


def _cmd_train(args: argparse.Namespace) -> int:
    feat_path = Path(args.features)
    out_path = Path(args.out)
    if not feat_path.is_file():
        print(f"error: features file not found: {feat_path}", file=sys.stderr)
        return 2

    print(f"loading features from {feat_path} ...", file=sys.stderr)
    df = pd.read_parquet(feat_path)
    print(f"  {len(df)} rows × {len(df.columns)} cols", file=sys.stderr)

    print("training Isolation Forest ...", file=sys.stderr)
    trained = train_isolation_forest(
        df,
        n_estimators=args.n_estimators,
        contamination=args.contamination,
        random_state=args.seed,
    )
    print(
        f"  trained on {trained.n_train_samples} samples, "
        f"calibration: normal={trained.decision_at_p_normal:.4f} "
        f"outlier={trained.decision_at_p_outlier:.4f}",
        file=sys.stderr,
    )
    trained.save(out_path)
    print(f"saved -> {out_path}", file=sys.stderr)
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    feat_path = Path(args.features)
    model_path = Path(args.model)
    out_path = Path(args.out)
    if not feat_path.is_file():
        print(f"error: features file not found: {feat_path}", file=sys.stderr)
        return 2
    if not model_path.is_file():
        print(f"error: model file not found: {model_path}", file=sys.stderr)
        return 2

    df = pd.read_parquet(feat_path)
    trained = TrainedIsolationForest.load(model_path)

    # IF score
    score_if = trained.score(df)

    # Rules
    rules_df = score_rules(df)

    out = df.copy()
    out["score_if"] = score_if
    out["score_rules"] = rules_df["score_rules"].to_numpy()
    out["rule_hits"] = rules_df["rule_hits"].to_numpy()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)

    n = len(out)
    print(
        f"scored {n} events -> {out_path}\n"
        f"  IF: max={out['score_if'].max():.3f} "
        f"mean={out['score_if'].mean():.3f}\n"
        f"  rules: max={out['score_rules'].max():.3f} "
        f"hits={(out['score_rules'] > 0).sum()}",
        file=sys.stderr,
    )
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    scored_path = Path(args.scored)
    truth_path = Path(args.truth)
    if not scored_path.is_file():
        print(f"error: scored file not found: {scored_path}", file=sys.stderr)
        return 2
    if not truth_path.is_file():
        print(f"error: truth file not found: {truth_path}", file=sys.stderr)
        return 2

    df = pd.read_parquet(scored_path)
    truth = load_truth(truth_path)

    thresholds = (0.3, 0.5, 0.7)
    metrics_if = evaluate_thresholds(
        df_features=df, score_column="score_if",
        truth=truth, thresholds=thresholds,
    )
    metrics_rules = evaluate_thresholds(
        df_features=df, score_column="score_rules",
        truth=truth, thresholds=thresholds,
    )

    table = metrics_to_dataframe(metrics_if + metrics_rules)
    cols = [
        "score_column", "threshold", "true_positives", "false_positives",
        "false_negatives", "precision", "recall", "f1",
        "scenario_detected", "max_attack_score", "max_normal_score",
    ]
    print(f"\n=== {truth['scenario']} ===")
    print(table[cols].to_string(index=False))

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.out, index=False)
        print(f"\n  metrics -> {args.out}", file=sys.stderr)
    return 0


def _cmd_evaluate_all(args: argparse.Namespace) -> int:
    scored_dir = Path(args.scored_dir)
    truth_dir = Path(args.truth_dir)
    if not scored_dir.is_dir():
        print(f"error: scored_dir not found: {scored_dir}", file=sys.stderr)
        return 2
    if not truth_dir.is_dir():
        print(f"error: truth_dir not found: {truth_dir}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for truth_path in sorted(truth_dir.glob("test_*.truth.json")):
        scenario = truth_path.stem.replace(".truth", "").replace("test_", "")
        scored_path = scored_dir / f"test_{scenario}.scored.parquet"
        if not scored_path.is_file():
            print(
                f"  skipping {scenario} — no scored parquet at {scored_path}",
                file=sys.stderr,
            )
            continue

        df = pd.read_parquet(scored_path)
        truth = load_truth(truth_path)
        thresholds = (0.3, 0.5, 0.7)
        metrics_if = evaluate_thresholds(
            df_features=df, score_column="score_if",
            truth=truth, thresholds=thresholds,
        )
        metrics_rules = evaluate_thresholds(
            df_features=df, score_column="score_rules",
            truth=truth, thresholds=thresholds,
        )
        for m in metrics_if + metrics_rules:
            rows.append(asdict(m))

    if not rows:
        print("no scenarios evaluated", file=sys.stderr)
        return 1

    df_all = pd.DataFrame(rows)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_all.to_csv(out_path, index=False)

    # Compact summary on stdout: per scenario per score, the best threshold's
    # F1 score, and whether scenario_detected at expected_min_score.
    print("\n=== Summary ===")
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
        prog="models.cli",
        description="Train, score, and evaluate detection models.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_train = sub.add_parser("train", help="Train an Isolation Forest.")
    p_train.add_argument("--features", required=True,
                         help="Path to TRAIN feature parquet")
    p_train.add_argument("--out", required=True,
                         help="Output joblib path")
    p_train.add_argument("--n-estimators", type=int, default=200)
    p_train.add_argument("--contamination", type=float, default=0.01)
    p_train.add_argument("--seed", type=int, default=42)
    p_train.set_defaults(func=_cmd_train)

    p_score = sub.add_parser(
        "score",
        help="Score a feature parquet with the trained IF + rules.",
    )
    p_score.add_argument("--features", required=True)
    p_score.add_argument("--model", required=True)
    p_score.add_argument("--out", required=True)
    p_score.set_defaults(func=_cmd_score)

    p_eval = sub.add_parser(
        "evaluate",
        help="Compute precision/recall/F1 against a truth.json.",
    )
    p_eval.add_argument("--scored", required=True)
    p_eval.add_argument("--truth", required=True)
    p_eval.add_argument("--out", default=None,
                        help="Optional CSV output for metrics")
    p_eval.set_defaults(func=_cmd_evaluate)

    p_eval_all = sub.add_parser(
        "evaluate-all",
        help="Evaluate all scored scenarios in a directory.",
    )
    p_eval_all.add_argument("--scored-dir", required=True)
    p_eval_all.add_argument("--truth-dir", required=True)
    p_eval_all.add_argument("--out", required=True)
    p_eval_all.set_defaults(func=_cmd_evaluate_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())