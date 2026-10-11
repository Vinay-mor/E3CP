"""Run paired multi-seed experiments and consolidation ablations for E3CP.

Each master seed generates one heterogeneous node fleet and five workload traces.
Every policy is evaluated against the same five traces for a given seed. Reported
standard deviations are across seed-level means; they are descriptive, not confidence
intervals. Bootstrap intervals are computed for paired between-policy differences.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import random
import statistics as stats
import subprocess
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
METRICS = [
    "energy_kwh", "avg_latency_ms", "sla_violation_pct", "avg_active_nodes",
    "avg_utilization_pct", "missing_image_layer_events", "blocked_requests", "migrations",
]
POLICIES = [
    "First-Fit",
    "First-Fit+Consolidation",
    "Latency-Aware",
    "Latency-Aware+Consolidation",
    "Min-Energy",
    "Min-Energy+Consolidation",
    "E3CP-NoConsolidation",
    "E3CP",
]


def load_simulator():
    spec = importlib.util.spec_from_file_location("e3cp_simulation", HERE / "e3cp_simulation.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load e3cp_simulation.py")
    sim = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = sim
    spec.loader.exec_module(sim)
    sim.POLICY_FN.update({
        "E3CP-NoConsolidation": sim.place_e3cp,
        "First-Fit+Consolidation": sim.place_first_fit,
        "Latency-Aware+Consolidation": sim.place_latency_aware,
        "Min-Energy+Consolidation": sim.place_min_energy,
    })
    return sim


def generate_dataset(seed: int, outdir: Path, num_traces: int, num_nodes: int) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(HERE / "gen_dataset.py"), "--seed", str(seed),
           "--output-dir", str(outdir), "--num-traces", str(num_traces),
           "--num-nodes", str(num_nodes)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def bootstrap_ci(values: list[float], seed: int = 8128, reps: int = 20000) -> tuple[float, float]:
    """Percentile bootstrap CI for mean; descriptive with small seed counts."""
    if not values:
        return (float("nan"), float("nan"))
    if len(values) == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    n = len(values)
    estimates = []
    for _ in range(reps):
        estimates.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    estimates.sort()
    return estimates[int(0.025 * reps)], estimates[min(reps - 1, int(0.975 * reps))]


def summarize_seed(policy_rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"seed": policy_rows[0]["seed"], "policy": policy_rows[0]["policy"],
                           "trace_count": len(policy_rows)}
    for metric in METRICS:
        vals = [float(row[metric]) for row in policy_rows]
        out[metric] = stats.mean(vals)
    return out


def aggregate_seed_results(seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for policy in POLICIES:
        group = [row for row in seed_rows if row["policy"] == policy]
        row: dict[str, Any] = {"policy": policy, "num_master_seeds": len(group)}
        for metric in METRICS:
            vals = [float(r[metric]) for r in group]
            row[f"{metric}_mean_across_seeds"] = stats.mean(vals)
            row[f"{metric}_sd_across_seeds"] = stats.stdev(vals) if len(vals) > 1 else 0.0
        output.append(row)
    return output


def get_metric_by_seed(seed_rows: list[dict[str, Any]], policy: str, metric: str) -> dict[int, float]:
    return {int(row["seed"]): float(row[metric]) for row in seed_rows if row["policy"] == policy}


def paired_effects(seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = [
        ("E3CP vs First-Fit", "E3CP", "First-Fit"),
        ("E3CP vs Min-Energy", "E3CP", "Min-Energy"),
        ("E3CP vs E3CP-NoConsolidation", "E3CP", "E3CP-NoConsolidation"),
        ("First-Fit+Consolidation vs First-Fit", "First-Fit+Consolidation", "First-Fit"),
        ("Latency-Aware+Consolidation vs Latency-Aware", "Latency-Aware+Consolidation", "Latency-Aware"),
        ("Min-Energy+Consolidation vs Min-Energy", "Min-Energy+Consolidation", "Min-Energy"),
    ]
    rows: list[dict[str, Any]] = []
    for pair_name, a, b in pairs:
        for metric in ["energy_kwh", "avg_latency_ms", "sla_violation_pct", "avg_active_nodes", "migrations"]:
            a_vals = get_metric_by_seed(seed_rows, a, metric)
            b_vals = get_metric_by_seed(seed_rows, b, metric)
            seeds = sorted(set(a_vals) & set(b_vals))
            diffs = [a_vals[s] - b_vals[s] for s in seeds]
            low, high = bootstrap_ci(diffs, seed=8128 + len(rows))
            rows.append({
                "comparison": pair_name,
                "metric": metric,
                "policy_a": a,
                "policy_b": b,
                "direction": "policy_a_minus_policy_b",
                "mean_paired_difference": stats.mean(diffs),
                "bootstrap_95_low": low,
                "bootstrap_95_high": high,
                "num_paired_master_seeds": len(diffs),
                "interpretation_note": "Positive means policy_a has a larger metric than policy_b; CI is percentile bootstrap over paired seed means.",
            })
    return rows


def create_plots(overall_rows: list[dict[str, Any]], seed_rows: list[dict[str, Any]], outdir: Path) -> None:
    policy_order = POLICIES
    # Short plot labels preserve readability when the figures are reduced to paper width.
    short_labels = ["FF", "FF + C", "Latency", "Latency + C", "Min-Energy", "Min-E + C", "E3CP - NC", "E3CP"]
    lookup = {row["policy"]: row for row in overall_rows}
    x = list(range(len(policy_order)))

    energy = [lookup[p]["energy_kwh_mean_across_seeds"] for p in policy_order]
    energy_sd = [lookup[p]["energy_kwh_sd_across_seeds"] for p in policy_order]
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.bar(x, energy, yerr=energy_sd, capsize=3)
    ax.set_xticks(x, short_labels, fontsize=7.6)
    ax.set_ylabel("Modeled total energy (kWh per two-hour trace)", fontsize=8.5)
    ax.set_title("Modeled total energy across master seeds (mean ± SD)", fontsize=10)
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "fig_energy_multiseed.png", dpi=240)
    plt.close(fig)

    lat = [lookup[p]["avg_latency_ms_mean_across_seeds"] for p in policy_order]
    lat_sd = [lookup[p]["avg_latency_ms_sd_across_seeds"] for p in policy_order]
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.bar(x, lat, yerr=lat_sd, capsize=3)
    ax.set_xticks(x, short_labels, fontsize=7.6)
    ax.set_ylabel("Estimated placement latency (ms)", fontsize=8.5)
    ax.set_title("Estimated placement latency across master seeds (mean ± SD)", fontsize=10)
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "fig_latency_multiseed.png", dpi=240)
    plt.close(fig)

    sla = [lookup[p]["sla_violation_pct_mean_across_seeds"] for p in policy_order]
    sla_sd = [lookup[p]["sla_violation_pct_sd_across_seeds"] for p in policy_order]
    fig, ax = plt.subplots(figsize=(7.2, 4.3))
    ax.bar(x, sla, yerr=sla_sd, capsize=3)
    ax.set_xticks(x, short_labels, fontsize=7.6)
    ax.set_ylabel("Request-failure rate (%)", fontsize=8.5)
    ax.set_title("Request-failure rate across master seeds (mean ± SD)", fontsize=10)
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "fig_sla_multiseed.png", dpi=240)
    plt.close(fig)

    active = [lookup[p]["avg_active_nodes_mean_across_seeds"] for p in policy_order]
    active_sd = [lookup[p]["avg_active_nodes_sd_across_seeds"] for p in policy_order]
    fig, ax = plt.subplots(figsize=(7.2, 4.3))
    ax.bar(x, active, yerr=active_sd, capsize=3)
    ax.set_xticks(x, short_labels, fontsize=7.6)
    ax.set_ylabel("Mean powered-on nodes", fontsize=8.5)
    ax.set_title("Active nodes across master seeds (mean ± SD)", fontsize=10)
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "fig_active_multiseed.png", dpi=240)
    plt.close(fig)

    # Combined panel for the paper's Figure 5, generated directly from this run's
    # aggregate results (rather than retaining an image from an earlier run).
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.2, 3.7))
    ax1.bar(x, sla, yerr=sla_sd, capsize=2.5)
    ax1.set_xticks(x, short_labels, fontsize=6.5, rotation=35, ha="right")
    ax1.set_ylabel("Request-failure rate (%)", fontsize=8)
    ax1.set_title("Request failures", fontsize=9)
    ax1.tick_params(axis="y", labelsize=7.5)
    ax2.bar(x, active, yerr=active_sd, capsize=2.5)
    ax2.set_xticks(x, short_labels, fontsize=6.5, rotation=35, ha="right")
    ax2.set_ylabel("Mean powered-on nodes", fontsize=8)
    ax2.set_title("Powered-on nodes", fontsize=9)
    ax2.tick_params(axis="y", labelsize=7.5)
    fig.suptitle("Request failures and powered-on nodes across eight policy variants", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(outdir / "fig_sla_active_multiseed.png", dpi=240)
    plt.close(fig)

    plt.figure(figsize=(7.2, 5.0))
    for p in policy_order:
        e = lookup[p]["energy_kwh_mean_across_seeds"]
        l = lookup[p]["avg_latency_ms_mean_across_seeds"]
        plt.scatter(l, e, s=35)
        label = p.replace("+Consolidation", " + C").replace("E3CP-NoConsolidation", "E3CP - NC")
        plt.annotate(label, (l, e), fontsize=6.5, xytext=(3, 3), textcoords="offset points")
    plt.xlabel("Estimated placement latency (ms)", fontsize=8.5)
    plt.ylabel("Modeled total energy (kWh per two-hour trace)", fontsize=8.5)
    plt.title("Energy-latency trade-off across master seeds", fontsize=10)
    plt.tick_params(labelsize=8)
    plt.tight_layout()
    plt.savefig(outdir / "fig_energy_latency_multiseed.png", dpi=240)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run E3CP multi-seed experiments and consolidation ablations.")
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(42, 52)),
                        help="Master seeds to run (default: 42 through 51).")
    parser.add_argument("--num-traces", type=int, default=5, help="Workload traces per master seed (default: 5).")
    parser.add_argument("--num-nodes", type=int, default=30, help="Nodes per seed (default: 30).")
    parser.add_argument("--output-dir", default="experiment_output", help="Directory for datasets and results.")
    args = parser.parse_args()
    if not args.seeds or args.num_traces < 1 or args.num_nodes < 1:
        parser.error("Provide at least one seed and positive trace/node counts")

    outdir = Path(args.output_dir).resolve()
    dataset_root = outdir / "datasets"
    dataset_root.mkdir(parents=True, exist_ok=True)
    sim = load_simulator()
    trace_rows: list[dict[str, Any]] = []
    seed_rows: list[dict[str, Any]] = []

    for seed in args.seeds:
        seed_dir = dataset_root / f"seed_{seed}"
        generate_dataset(seed, seed_dir, args.num_traces, args.num_nodes)
        sim.NODES_CSV = str(seed_dir / "edge_nodes.csv")
        trace_files = sorted(seed_dir.glob("container_requests_trace*.csv"))
        if len(trace_files) != args.num_traces:
            raise RuntimeError(f"Expected {args.num_traces} traces at {seed_dir}; found {len(trace_files)}")
        seed_group_rows: list[dict[str, Any]] = []
        print(f"Seed {seed}: evaluating {args.num_traces} traces across {len(POLICIES)} policies...", flush=True)
        for policy in POLICIES:
            for trace_index, trace_path in enumerate(trace_files):
                sim.Container._next_id = 0
                by_interval = sim.load_requests_by_interval(str(trace_path))
                result = sim.run_one_trace(policy, by_interval)
                row: dict[str, Any] = {"seed": seed, "trace_index": trace_index,
                                       "trace_file": trace_path.name, "policy": policy}
                row.update({metric: result[metric] for metric in METRICS})
                trace_rows.append(row)
                seed_group_rows.append(row)
        # Average the five trace outcomes within each master seed, before comparing seeds.
        for policy in POLICIES:
            rows = [r for r in seed_group_rows if r["policy"] == policy]
            seed_rows.append(summarize_seed(rows))

    outdir.mkdir(parents=True, exist_ok=True)
    trace_fields = ["seed", "trace_index", "trace_file", "policy"] + METRICS
    seed_fields = ["seed", "policy", "trace_count"] + METRICS
    overall = aggregate_seed_results(seed_rows)
    overall_fields = ["policy", "num_master_seeds"] + [f"{m}_{s}" for m in METRICS for s in ("mean_across_seeds", "sd_across_seeds")]
    effect_rows = paired_effects(seed_rows)
    effect_fields = list(effect_rows[0].keys()) if effect_rows else []
    write_csv(outdir / "results_per_trace.csv", trace_fields, trace_rows)
    write_csv(outdir / "results_by_seed.csv", seed_fields, seed_rows)
    write_csv(outdir / "results_overall.csv", overall_fields, overall)
    write_csv(outdir / "paired_effects_bootstrap.csv", effect_fields, effect_rows)
    create_plots(overall, seed_rows, outdir)

    # Markdown summary for direct use when drafting the paper.
    lookup = {row["policy"]: row for row in overall}
    ff, e3, e3_no = lookup["First-Fit"], lookup["E3CP"], lookup["E3CP-NoConsolidation"]
    energy_reduction = 100 * (ff["energy_kwh_mean_across_seeds"] - e3["energy_kwh_mean_across_seeds"]) / ff["energy_kwh_mean_across_seeds"]
    latency_reduction = 100 * (ff["avg_latency_ms_mean_across_seeds"] - e3["avg_latency_ms_mean_across_seeds"]) / ff["avg_latency_ms_mean_across_seeds"]
    summary_lines = [
        "# E3CP multi-seed simulation report", "",
        f"- Master seeds: {', '.join(map(str, args.seeds))} ({len(args.seeds)} total).",
        f"- Per seed: {args.num_nodes} heterogeneous nodes, {args.num_traces} workload traces, 12 ten-minute intervals per trace.",
        f"- Total policy-trace runs: {len(trace_rows)}.",
        "- Each seed generates one fleet shared across its workload traces; policies are evaluated on paired traces.",
        "- Reported standard deviations are across master-seed means and are not confidence intervals.",
        "- Modeled total energy equals modeled awake-node energy plus the fixed migration-energy proxy for accepted container migrations.",
        "- Consolidation is accepted only when the estimated one-interval node-energy saving exceeds the migration-energy proxy; the estimate subtracts destination-node power increases.",
        "- Network energy, image-transfer energy, and sleep/wake-transition energy are not modeled.",
        "- The image metric counts missing image-layer events, not bytes or megabytes.",
        "- SLA failure rate is 100 × (placed requests exceeding estimated latency limits + blocked requests) / all arrived requests.",
        "",
        "## Headline descriptive comparison", "",
        f"- E3CP modeled total energy vs First-Fit: {energy_reduction:.2f}% lower on the across-seed means.",
        f"- E3CP estimated placement latency vs First-Fit: {latency_reduction:.2f}% lower on the across-seed means.",
        f"- E3CP mean active nodes: {e3['avg_active_nodes_mean_across_seeds']:.3f}; First-Fit: {ff['avg_active_nodes_mean_across_seeds']:.3f}.",
        f"- E3CP full vs no-consolidation energy: {e3['energy_kwh_mean_across_seeds']:.5f} vs {e3_no['energy_kwh_mean_across_seeds']:.5f} kWh.",
        "- These are synthetic-simulation outcomes and do not establish physical power savings or superiority on real edge hardware.",
        "",
        "## Output files", "",
        "- `results_per_trace.csv`: one row per policy, trace, and master seed.",
        "- `results_by_seed.csv`: per-policy averages over traces within each master seed.",
        "- `results_overall.csv`: means and standard deviations across master-seed means.",
        "- `paired_effects_bootstrap.csv`: paired per-seed differences with percentile bootstrap intervals.",
        "- `fig_energy_multiseed.png`, `fig_latency_multiseed.png`, `fig_sla_multiseed.png`, `fig_active_multiseed.png`, `fig_sla_active_multiseed.png`, `fig_energy_latency_multiseed.png`: figures generated directly from the current results.",
    ]
    (outdir / "REPORT.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(f"\nFinished. Results written to: {outdir}")
    print((outdir / "REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
