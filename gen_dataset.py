"""Generate a synthetic dataset for the E3CP placement simulator.

Defaults reproduce the original dataset generated with master seed 42.
"""
import argparse
import csv
import random
from pathlib import Path

NUM_NODES = 30
NUM_REGIONS = 6
NUM_LAYER_TYPES = 12
NUM_INTERVALS = 12
NUM_TRACES = 5
REQUESTS_PER_INTERVAL = (15, 30)
DEFAULT_MASTER_SEED = 42


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a reproducible synthetic E3CP dataset.")
    parser.add_argument("--seed", type=int, default=DEFAULT_MASTER_SEED,
                        help="Master RNG seed (default: 42).")
    parser.add_argument("--output-dir", default=".",
                        help="Directory in which CSV files are written (default: current directory).")
    parser.add_argument("--num-traces", type=int, default=NUM_TRACES,
                        help="Number of workload traces (default: 5).")
    parser.add_argument("--num-nodes", type=int, default=NUM_NODES,
                        help="Number of edge nodes (default: 30).")
    args = parser.parse_args()
    if args.num_traces < 1 or args.num_nodes < 1:
        parser.error("--num-traces and --num-nodes must be positive")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    # Generate one heterogeneous node fleet shared by all traces for this seed.
    with (output_dir / "edge_nodes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["node_id", "region", "cpu_cap_cores", "mem_cap_gb", "bw_cap_mbps",
                    "idle_power_w", "max_power_w", "reliability", "cached_layers"])
        for i in range(args.num_nodes):
            region = i % NUM_REGIONS
            cpu = round(rng.uniform(6, 40), 1)
            mem = round(rng.uniform(12, 80), 1)
            bw = round(rng.uniform(80, 600), 1)
            idle = round(rng.uniform(12, 45), 1)
            maxp = round(idle + rng.uniform(50, 160), 1)
            rel = round(rng.uniform(0.72, 0.997), 3)
            layers = sorted(rng.sample(range(NUM_LAYER_TYPES), k=rng.randint(2, 6)))
            w.writerow([f"N{i+1}", region, cpu, mem, bw, idle, maxp, rel,
                        "|".join(map(str, layers))])

    # Generate workload traces from the same continued RNG stream.
    for trace in range(args.num_traces):
        with (output_dir / f"container_requests_trace{trace}.csv").open(
                "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["request_id", "interval", "region", "cpu_req_cores", "mem_req_gb",
                        "bw_req_mbps", "latency_max_ms", "image_layers", "lifetime_intervals"])
            rid = 1
            for interval in range(NUM_INTERVALS):
                n_new = rng.randint(*REQUESTS_PER_INTERVAL)
                for _ in range(n_new):
                    region = rng.randrange(NUM_REGIONS)
                    cpu = round(rng.uniform(0.5, 4), 2)
                    mem = round(rng.uniform(1, 8), 2)
                    bw = round(rng.uniform(2, 25), 2)
                    lat = round(rng.uniform(12, 130), 1)
                    layers = sorted(rng.sample(range(NUM_LAYER_TYPES), k=rng.randint(1, 3)))
                    lifetime = rng.randint(1, 5)
                    w.writerow([f"T{trace}-R{rid}", interval, region, cpu, mem, bw, lat,
                                "|".join(map(str, layers)), lifetime])
                    rid += 1

    print(f"Generated {args.num_nodes} nodes across {NUM_REGIONS} regions, "
          f"{args.num_traces} workload traces x {NUM_INTERVALS} intervals each; seed={args.seed}. "
          f"Output: {output_dir}")


if __name__ == "__main__":
    main()
