"""
E3CP: Energy-Efficient Container Placement for Edge Computing
================================================================
Reproducible Python simulation comparing four placement policies:
  - First-Fit       (capacity-only, no energy/latency awareness)
  - Latency-Aware    (minimizes estimated latency only)
  - Min-Energy       (minimizes incremental power only)
  - E3CP             (QoS-feasibility filter + weighted multi-objective score
                       + dynamic consolidation / migration / sleep states)

This is a from-scratch simulation model built from the design described in
the paper "Energy-Efficient Container Placement for Edge Computing" (E3CP).
It evaluates the behavior of the implemented heuristic under explicit model
assumptions. Results are deterministic for the supplied CSV traces and parameter
settings; energy and latency are model estimates, not hardware measurements.

Dataset: reads the fixed files produced by gen_dataset.py --
  edge_nodes.csv                     -- the node fleet (one fixed dataset)
  container_requests_trace{0..N}.csv -- N independent workload replicates

The main script reports descriptive mean and standard deviation across supplied
workload traces. Those standard deviations are not confidence intervals.

Outputs: a printed table, results CSV, charts, and a report. Energy includes
modeled node energy plus the fixed migration-energy proxy for migrations that
are accepted. Network, image-transfer, and sleep/wake-transition energy are not
modeled. All reported values are simulation estimates, not hardware measurements.
"""

import random
import statistics as stats
import csv
import os
import glob
import copy
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
NODES_CSV = os.path.join(HERE, "edge_nodes.csv")
TRACE_FILES = sorted(glob.glob(os.path.join(HERE, "container_requests_trace*.csv")))

# ----------------------------------------------------------------------
# 1. GLOBAL SIMULATION PARAMETERS  (Section IX.A of the paper)
# ----------------------------------------------------------------------
NUM_INTERVALS = 12
INTERVAL_HOURS = 10 / 60.0          # 10-minute intervals
NUM_LAYER_TYPES = 12
POLICIES = ["First-Fit", "Latency-Aware", "Min-Energy", "E3CP"]

ALPHA = 2.0                          # power-curve exponent (Section V.A)
RELIABILITY_MIN = 0.80               # hard QoS threshold used by E3CP
LOW_UTIL_THRESHOLD = 0.20            # underload trigger for consolidation
MIGRATION_ENERGY_COST_KWH = 0.0006   # fixed overhead per migrated container
LAYER_TRANSFER_MS = 6.0              # latency penalty per missing image layer

# Default E3CP objective weights (Section V.B) -- must sum to 1.0
DEFAULT_WEIGHTS = dict(W_E=0.35, W_L=0.25, W_U=0.15, W_T=0.10, W_I=0.10, W_R=0.05)


# ----------------------------------------------------------------------
# 2. DATA MODELS
# ----------------------------------------------------------------------
class Node:
    __slots__ = ("id", "region", "cpu_cap", "mem_cap", "bw_cap", "idle_power",
                 "max_power", "reliability", "cached_layers", "cpu_used",
                 "mem_used", "bw_used", "hosted", "asleep")

    def utilization(self, extra_cpu=0.0, extra_mem=0.0, extra_bw=0.0):
        u_cpu = (self.cpu_used + extra_cpu) / self.cpu_cap
        u_mem = (self.mem_used + extra_mem) / self.mem_cap
        u_bw = (self.bw_used + extra_bw) / self.bw_cap
        return max(u_cpu, u_mem, u_bw)     # bottleneck resource drives power

    def fits(self, c):
        return (self.cpu_used + c.cpu <= self.cpu_cap and
                self.mem_used + c.mem <= self.mem_cap and
                self.bw_used + c.bw <= self.bw_cap)

    def place(self, c):
        self.cpu_used += c.cpu
        self.mem_used += c.mem
        self.bw_used += c.bw
        self.hosted[c.id] = c
        self.cached_layers |= c.layers   # deploying a container caches its layers

    def remove(self, c):
        self.cpu_used -= c.cpu
        self.mem_used -= c.mem
        self.bw_used -= c.bw
        del self.hosted[c.id]


class Container:
    __slots__ = ("id", "cpu", "mem", "bw", "latency_max", "region", "layers", "lifetime")
    _next_id = 0

    def __init__(self, row):
        Container._next_id += 1
        self.id = Container._next_id
        self.cpu = float(row["cpu_req_cores"])
        self.mem = float(row["mem_req_gb"])
        self.bw = float(row["bw_req_mbps"])
        self.latency_max = float(row["latency_max_ms"])
        self.region = int(row["region"])
        self.layers = set(int(x) for x in row["image_layers"].split("|") if x != "")
        self.lifetime = int(row["lifetime_intervals"])


def power(node, u):
    """Load-dependent power model, Section V.A: P_i(u)=P_idle+(P_max-P_idle)*u^alpha"""
    u = max(0.0, min(1.0, u))
    return node.idle_power + (node.max_power - node.idle_power) * (u ** ALPHA)


def region_base_latency(r1, r2):
    return 5.0 + 8.0 * abs(r1 - r2)


def estimate_latency(node, c, projected_u):
    congestion = 50.0 * (projected_u ** 2)
    missing_layers = len(c.layers - node.cached_layers)
    return region_base_latency(node.region, c.region) + congestion + missing_layers * LAYER_TRANSFER_MS


def normalize(values):
    """Min-max normalize a dict {key: value} to [0,1]; flat if no spread."""
    lo, hi = min(values.values()), max(values.values())
    if hi - lo < 1e-9:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


# ----------------------------------------------------------------------
# Dataset loaders -- fixed CSV files so results are reproducible and the
# dataset itself can be shown to faculty as a real artifact.
# ----------------------------------------------------------------------
def load_nodes():
    nodes = []
    with open(NODES_CSV) as f:
        for row in csv.DictReader(f):
            n = Node.__new__(Node)
            n.id = int(row["node_id"].lstrip("N")) - 1
            n.region = int(row["region"])
            n.cpu_cap = float(row["cpu_cap_cores"])
            n.mem_cap = float(row["mem_cap_gb"])
            n.bw_cap = float(row["bw_cap_mbps"])
            n.idle_power = float(row["idle_power_w"])
            n.max_power = float(row["max_power_w"])
            n.reliability = float(row["reliability"])
            n.cached_layers = set(int(x) for x in row["cached_layers"].split("|") if x != "")
            n.cpu_used, n.mem_used, n.bw_used = 0.0, 0.0, 0.0
            n.hosted = {}
            n.asleep = False
            nodes.append(n)
    return nodes


def load_requests_by_interval(path):
    by_interval = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            by_interval.setdefault(int(row["interval"]), []).append(row)
    return by_interval


# ----------------------------------------------------------------------
# 3. PLACEMENT POLICIES
# ----------------------------------------------------------------------
def qos_feasible(node, c):
    """Return whether a node satisfies the simulator's E3CP latency/reliability gate."""
    if not node.fits(c) or node.reliability < RELIABILITY_MIN:
        return False
    projected_u = node.utilization(c.cpu, c.mem, c.bw)
    return estimate_latency(node, c, projected_u) <= c.latency_max


def candidate_nodes(nodes, c, enforce_qos):
    cands = []
    for n in nodes:
        if n.asleep or not n.fits(c):
            continue
        if enforce_qos and not qos_feasible(n, c):
            continue
        cands.append(n)
    return cands


def place_first_fit(nodes, c, weights=None):
    cands = candidate_nodes(nodes, c, enforce_qos=False)
    return cands[0] if cands else None


def place_latency_aware(nodes, c, weights=None):
    cands = candidate_nodes(nodes, c, enforce_qos=False)
    if not cands:
        return None
    return min(cands, key=lambda n: estimate_latency(n, c, n.utilization(c.cpu, c.mem, c.bw)))


def place_min_energy(nodes, c, weights=None):
    cands = candidate_nodes(nodes, c, enforce_qos=False)
    if not cands:
        return None
    def delta_p(n):
        return power(n, n.utilization(c.cpu, c.mem, c.bw)) - power(n, n.utilization())
    return min(cands, key=delta_p)


def select_e3cp_candidate(cands, c, weights=None):
    """Select the lowest weighted-score node from an already-filtered candidate list.

    The list may contain sleeping nodes only during a wake-up decision. Normal placement
    passes candidates from awake nodes, so this helper does not change node state.
    """
    if not cands:
        return None
    w = weights or DEFAULT_WEIGHTS
    delta_p, lat, util, transfer, interf = {}, {}, {}, {}, {}
    for n in cands:
        u0 = n.utilization()
        u1 = n.utilization(c.cpu, c.mem, c.bw)
        delta_p[n.id] = power(n, u1) - power(n, u0)
        lat[n.id] = estimate_latency(n, c, u1)
        util[n.id] = u1
        transfer[n.id] = len(c.layers - n.cached_layers)
        interf[n.id] = len(n.hosted) / max(1, n.cpu_cap)

    e_n, l_n, u_n, t_n = normalize(delta_p), normalize(lat), normalize(util), normalize(transfer)
    i_n = normalize(interf)
    by_id = {n.id: n for n in cands}
    score = {nid: w["W_E"] * e_n[nid] + w["W_L"] * l_n[nid] + w["W_U"] * u_n[nid]
             + w["W_T"] * t_n[nid] + w["W_I"] * i_n[nid]
             + w["W_R"] * (1 - by_id[nid].reliability)
             for nid in by_id}
    return by_id[min(score, key=score.get)]


def place_e3cp(nodes, c, weights=None):
    cands = candidate_nodes(nodes, c, enforce_qos=True)
    if not cands:                      # relaxation is allowed only after wake-up considers sleepers
        cands = candidate_nodes(nodes, c, enforce_qos=False)
    return select_e3cp_candidate(cands, c, weights)


POLICY_FN = {
    "First-Fit": place_first_fit,
    "Latency-Aware": place_latency_aware,
    "Min-Energy": place_min_energy,
    "E3CP": place_e3cp,
}


# ----------------------------------------------------------------------
# 4. CONSOLIDATION -- shared optional operation for policy ablations
# ----------------------------------------------------------------------
def try_consolidate(nodes):
    """Try to empty underloaded nodes only when estimated net energy saving is positive.

    The projected saving subtracts destination-node power increases and the fixed
    migration-energy proxy. It is a one-interval estimate, not a hardware measurement.
    """
    migrations = 0
    migration_energy_kwh = 0.0
    active = [n for n in nodes if not n.asleep]

    for n in active:
        if n.asleep:
            continue
        if len(n.hosted) == 0:
            n.asleep = True
            continue
        if n.utilization() >= LOW_UTIL_THRESHOLD:
            continue

        others = [o for o in active if o.id != n.id and not o.asleep]
        containers = list(n.hosted.values())
        if not others:
            continue

        plan = {}
        feasible_all = True
        temp_alloc = {o.id: (o.cpu_used, o.mem_used, o.bw_used) for o in others}
        temp_layers = {o.id: set(o.cached_layers) for o in others}
        temp_migrants = {o.id: [] for o in others}
        migration_missing_layers = {}

        for c in containers:
            dest = None
            for o in others:
                cu, mu, bu = temp_alloc[o.id]
                if (cu + c.cpu <= o.cpu_cap and
                    mu + c.mem <= o.mem_cap and
                    bu + c.bw <= o.bw_cap and
                    o.reliability >= RELIABILITY_MIN):
                    u_proj = max((cu + c.cpu) / o.cpu_cap,
                                 (mu + c.mem) / o.mem_cap,
                                 (bu + c.bw) / o.bw_cap)
                    missing = len(c.layers - temp_layers[o.id])
                    lat_proj = region_base_latency(o.region, c.region) + 50.0 * (u_proj ** 2) + missing * LAYER_TRANSFER_MS
                    if lat_proj <= c.latency_max:
                        dest = o
                        temp_alloc[o.id] = (cu + c.cpu, mu + c.mem, bu + c.bw)
                        migration_missing_layers[c.id] = missing
                        temp_layers[o.id].update(c.layers)
                        temp_migrants[o.id].append(c)
                        break
            if dest is None:
                feasible_all = False
                break
            plan[c.id] = dest

        if not feasible_all:
            continue

        # Recheck all colocated workloads at final projected utilization; adding
        # later migrants can otherwise invalidate an earlier container's latency.
        for o in others:
            cu, mu, bu = temp_alloc[o.id]
            u_final = max(cu / o.cpu_cap, mu / o.mem_cap, bu / o.bw_cap)
            all_hosted = list(o.hosted.values()) + temp_migrants[o.id]
            migrant_ids = {c.id for c in temp_migrants[o.id]}
            for c in all_hosted:
                missing = migration_missing_layers[c.id] if c.id in migrant_ids else 0
                lat_final = region_base_latency(o.region, c.region) + 50.0 * (u_final ** 2) + missing * LAYER_TRANSFER_MS
                if lat_final > c.latency_max or o.reliability < RELIABILITY_MIN:
                    feasible_all = False
                    break
            if not feasible_all:
                break
        if not feasible_all:
            continue

        # Compare total awake-node power before/after the proposed consolidation
        # for one 10-minute interval, then subtract the migration proxy.
        before_kwh = sum(power(o, o.utilization()) * INTERVAL_HOURS / 1000.0
                         for o in nodes if not o.asleep)
        after_kwh = 0.0
        for o in others:
            cu, mu, bu = temp_alloc[o.id]
            u_after = max(cu / o.cpu_cap, mu / o.mem_cap, bu / o.bw_cap)
            after_kwh += power(o, u_after) * INTERVAL_HOURS / 1000.0
        # Nodes other than source and destinations remain awake at current load.
        after_kwh += sum(power(o, o.utilization()) * INTERVAL_HOURS / 1000.0
                         for o in nodes if not o.asleep and o.id != n.id and o.id not in temp_alloc)
        gross_saving_kwh = before_kwh - after_kwh
        migration_cost_kwh = MIGRATION_ENERGY_COST_KWH * len(containers)
        if gross_saving_kwh <= migration_cost_kwh:
            continue

        for c in containers:
            dest = plan[c.id]
            n.remove(c)
            dest.place(c)
            migrations += 1
        n.asleep = True
        # This assumed overhead is included in the total modeled-energy metric.
        try_cost = migration_cost_kwh
        migration_energy_kwh += try_cost

    return migrations, migration_energy_kwh


def _best_capacity_node(policy, nodes, c, weights=None):
    """Choose one sleeping node to wake, without waking unrelated nodes."""
    candidates = [n for n in nodes if n.asleep and n.fits(c)]
    if not candidates:
        return None
    if policy == "First-Fit" or policy == "First-Fit+Consolidation":
        return min(candidates, key=lambda n: n.id)
    if policy == "Latency-Aware" or policy == "Latency-Aware+Consolidation":
        return min(candidates, key=lambda n: estimate_latency(
            n, c, n.utilization(c.cpu, c.mem, c.bw)))
    if policy == "Min-Energy" or policy == "Min-Energy+Consolidation":
        return min(candidates, key=lambda n: power(n, n.utilization(c.cpu, c.mem, c.bw)) - power(n, n.utilization()))
    return select_e3cp_candidate(candidates, c, weights)


def wake_for_request(policy, nodes, c, weights=None):
    """Wake a sleeping node only when useful for this request.

    E3CP first checks its QoS-feasible awake candidates. If none exist, it checks
    sleeping nodes for a QoS-feasible destination and wakes the best of those before
    allowing the explicitly documented fallback. Other policies wake only when no
    awake node has enough capacity.
    """
    awake = [n for n in nodes if not n.asleep]
    if policy in {"E3CP", "E3CP-NoConsolidation"}:
        if any(qos_feasible(n, c) for n in awake):
            return
        sleeping_qos = [n for n in nodes if n.asleep and qos_feasible(n, c)]
        if sleeping_qos:
            chosen = select_e3cp_candidate(sleeping_qos, c, weights)
            chosen.asleep = False
            return
        # No QoS-feasible host exists. Preserve the fallback, but ensure there is
        # an awake capacity-feasible host before marking the request blocked.
        if any(n.fits(c) for n in awake):
            return
        chosen = _best_capacity_node(policy, nodes, c, weights)
        if chosen is not None:
            chosen.asleep = False
        return

    if any(n.fits(c) for n in awake):
        return
    chosen = _best_capacity_node(policy, nodes, c, weights)
    if chosen is not None:
        chosen.asleep = False


# ----------------------------------------------------------------------
# 5. SIMULATION LOOP (single trace, single policy)
# ----------------------------------------------------------------------
def run_one_trace(policy, requests_by_interval, weights=None, track_series=False):
    nodes = load_nodes()
    place_fn = POLICY_FN[policy]

    total_energy_kwh, latencies = 0.0, []
    sla_violations, total_requests, blocked, missing_layer_events = 0, 0, 0, 0
    active_node_samples, util_samples, migrations_total = [], [], 0
    series_energy, series_active = [], []

    for interval in range(NUM_INTERVALS):
        for row in requests_by_interval.get(interval, []):
            c = Container(row)
            total_requests += 1

            # Resolve sleeping-node choices before calling a placement policy. For
            # E3CP, this includes checking sleeping nodes against the QoS gate before
            # its fallback can select a QoS-infeasible awake candidate.
            wake_for_request(policy, nodes, c, weights)

            dest = place_fn(nodes, c, weights)
            if dest is None:
                blocked += 1
                # A request that cannot be placed has not met its service obligation.
                sla_violations += 1
                continue

            u_proj = dest.utilization(c.cpu, c.mem, c.bw)
            lat = estimate_latency(dest, c, u_proj)
            latencies.append(lat)
            if lat > c.latency_max:
                sla_violations += 1
            missing_layer_events += len(c.layers - dest.cached_layers)
            dest.place(c)

        interval_node_energy = sum(power(n, n.utilization()) * INTERVAL_HOURS / 1000.0
                                   for n in nodes if not n.asleep)

        # Keep node-count/utilization metrics aligned with the same powered-on
        # snapshot used for the interval's node-energy estimate. Consolidation at
        # the boundary affects the NEXT interval, not the interval just measured.
        n_active = sum(1 for n in nodes if not n.asleep)
        active_node_samples.append(n_active)
        busy = [n.utilization() for n in nodes if not n.asleep]
        if busy:
            util_samples.append(stats.mean(busy))

        # Close the interval and release requests whose modeled lifetime has ended
        # before consolidation is evaluated at the interval boundary. This avoids
        # migrating containers that would immediately expire.
        for n in nodes:
            for cid, c in list(n.hosted.items()):
                c.lifetime -= 1
                if c.lifetime <= 0:
                    n.remove(c)

        interval_migration_energy = 0.0
        # Consolidation's acceptance test assumes savings over one subsequent
        # interval. At the final boundary no such interval is simulated, so do not
        # migrate or charge a migration-energy proxy there.
        is_final_interval = interval == NUM_INTERVALS - 1
        consolidation_enabled = policy == "E3CP" or policy.endswith("+Consolidation")
        if consolidation_enabled and not is_final_interval:
            migrations_this_interval, interval_migration_energy = try_consolidate(nodes)
            migrations_total += migrations_this_interval
        interval_energy = interval_node_energy + interval_migration_energy
        total_energy_kwh += interval_energy

        if track_series:
            series_energy.append(interval_energy)
            series_active.append(n_active)

    result = {
        "energy_kwh": total_energy_kwh,
        "avg_latency_ms": stats.mean(latencies) if latencies else 0.0,
        "sla_violation_pct": 100.0 * sla_violations / total_requests if total_requests else 0.0,
        "avg_active_nodes": stats.mean(active_node_samples),
        "avg_utilization_pct": 100.0 * stats.mean(util_samples) if util_samples else 0.0,
        "missing_image_layer_events": missing_layer_events,
        "blocked_requests": blocked,
        "migrations": migrations_total,
    }
    if track_series:
        result["series_energy"] = series_energy
        result["series_active"] = series_active
    return result


# ----------------------------------------------------------------------
# 6. RUN ACROSS ALL TRACES -> mean +/- std  (paired comparison, Section IX.D)
# ----------------------------------------------------------------------
METRIC_KEYS = ["energy_kwh", "avg_latency_ms", "sla_violation_pct", "avg_active_nodes",
               "avg_utilization_pct", "missing_image_layer_events", "blocked_requests", "migrations"]


def run_all():
    traces = [load_requests_by_interval(p) for p in TRACE_FILES]
    per_policy_runs = {p: [] for p in POLICIES}
    series = {}   # time-series from trace 0, for the dynamics plots

    for p in POLICIES:
        Container._next_id = 0
        for i, trace in enumerate(traces):
            Container._next_id = 0
            track = (i == 0)
            r = run_one_trace(p, trace, track_series=track)
            if track:
                series[p] = (r.pop("series_energy"), r.pop("series_active"))
            per_policy_runs[p].append(r)

    summary = {}
    for p in POLICIES:
        summary[p] = {}
        for k in METRIC_KEYS:
            vals = [r[k] for r in per_policy_runs[p]]
            summary[p][k] = {"mean": stats.mean(vals),
                              "std": stats.pstdev(vals) if len(vals) > 1 else 0.0}
    return summary, series, len(traces)


def run_weight_sensitivity(trace0):
    """Sweep w_E (energy weight) vs w_L (latency weight), keeping the other
    four weights fixed, and see how E3CP moves along the energy-latency
    trade-off (Section XI.D, item 11 of the paper)."""
    points = []
    base = DEFAULT_WEIGHTS
    fixed_total = base["W_U"] + base["W_T"] + base["W_I"] + base["W_R"]
    el_total = 1.0 - fixed_total  # w_E + w_L budget
    for w_e in [0.10, 0.20, 0.30, 0.40, 0.50, 0.60]:
        w_e = min(w_e, el_total)
        weights = dict(base)
        weights["W_E"] = w_e
        weights["W_L"] = el_total - w_e
        Container._next_id = 0
        r = run_one_trace("E3CP", trace0, weights=weights)
        points.append((w_e, r["energy_kwh"], r["avg_latency_ms"]))
    return points


# ----------------------------------------------------------------------
# 7. REPORTING: table, CSV, plots, text report
# ----------------------------------------------------------------------
def print_table(summary, n_traces):
    print(f"Results averaged over {n_traces} workload traces (mean ± SD)\n")
    labels = {
        "energy_kwh": "total_energy_kwh",
        "avg_latency_ms": "latency_ms",
        "sla_violation_pct": "SLA_failure_pct",
        "avg_active_nodes": "active_nodes",
        "avg_utilization_pct": "utilization_pct",
        "missing_image_layer_events": "missing_layers",
        "blocked_requests": "blocked_requests",
        "migrations": "migrated_containers",
    }
    cols = METRIC_KEYS
    header = f"{'Policy':<20}" + "".join(f"{labels[c]:>23}" for c in cols)
    print(header)
    print("-" * len(header))
    for p in POLICIES:
        row = f"{p:<20}"
        for c in cols:
            m, s = summary[p][c]["mean"], summary[p][c]["std"]
            row += f"{m:>10.4f} ± {s:<8.4f}"
        print(row)

    ff, e3 = summary["First-Fit"], summary["E3CP"]
    er = 100 * (ff["energy_kwh"]["mean"] - e3["energy_kwh"]["mean"]) / ff["energy_kwh"]["mean"]
    lr = 100 * (ff["avg_latency_ms"]["mean"] - e3["avg_latency_ms"]["mean"]) / ff["avg_latency_ms"]["mean"]
    print(f"\nE3CP vs First-Fit: modeled total energy {er:.1f}% lower; estimated latency {lr:.1f}% lower")
    return er, lr


def save_csv(summary, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["policy"] + [f"{k}_{stat}" for k in METRIC_KEYS for stat in ("mean", "std")])
        for p in POLICIES:
            row = [p]
            for k in METRIC_KEYS:
                row += [summary[p][k]["mean"], summary[p][k]["std"]]
            w.writerow(row)


def make_plots(summary, series, sensitivity, outdir):
    colors = {"First-Fit": "#8899aa", "Latency-Aware": "#e8a33d",
              "Min-Energy": "#4c9f70", "E3CP": "#3b6fd6"}

    def bar_with_err(metric, ylabel, title, fname, fmt="{:.4f}"):
        plt.figure(figsize=(6.5, 4.2))
        means = [summary[p][metric]["mean"] for p in POLICIES]
        stds = [summary[p][metric]["std"] for p in POLICIES]
        plt.bar(POLICIES, means, yerr=stds, capsize=6, color=[colors[p] for p in POLICIES])
        plt.ylabel(ylabel)
        plt.title(title)
        for i, v in enumerate(means):
            plt.text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=9)
        plt.tight_layout()
        plt.savefig(f"{outdir}/{fname}", dpi=150)
        plt.close()

    bar_with_err("energy_kwh", "Modeled total energy (node + migration proxy, kWh)", "Modeled Total Energy (mean ± SD across traces)",
                 "fig3_energy_comparison.png")
    bar_with_err("avg_latency_ms", "Average latency (ms)", "Average Latency Comparison (mean ± std across traces)",
                 "fig4_latency_comparison.png", fmt="{:.2f}")

    # Fig 5: trade-off scatter + weight-sensitivity curve for E3CP
    plt.figure(figsize=(6.5, 5))
    for p in POLICIES:
        x = summary[p]["avg_latency_ms"]["mean"]
        y = summary[p]["energy_kwh"]["mean"]
        plt.scatter(x, y, s=140, color=colors[p], label=p, zorder=3)
        plt.annotate(p, (x, y), textcoords="offset points", xytext=(6, 6), fontsize=9)
    if sensitivity:
        sx = [pt[2] for pt in sensitivity]
        sy = [pt[1] for pt in sensitivity]
        plt.plot(sx, sy, "--", color="#3b6fd6", alpha=0.5, zorder=1)
        plt.scatter(sx, sy, s=30, color="#3b6fd6", alpha=0.5, zorder=2, label="E3CP (w_E sweep)")
        for w_e, e, l in sensitivity:
            plt.annotate(f"wE={w_e:.1f}", (l, e), fontsize=6, alpha=0.7,
                         textcoords="offset points", xytext=(4, -8))
    plt.xlabel("Average latency (ms)")
    plt.ylabel("Modeled total energy (node + migration proxy, kWh)")
    plt.title("Energy-Latency Trade-off (+ E3CP weight sensitivity)")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(f"{outdir}/fig5_tradeoff.png", dpi=150)
    plt.close()

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    axes[0].bar(POLICIES, [summary[p]["sla_violation_pct"]["mean"] for p in POLICIES],
                yerr=[summary[p]["sla_violation_pct"]["std"] for p in POLICIES],
                capsize=6, color=[colors[p] for p in POLICIES])
    axes[0].set_title("SLA Violation Rate (%)")
    axes[1].bar(POLICIES, [summary[p]["avg_active_nodes"]["mean"] for p in POLICIES],
                yerr=[summary[p]["avg_active_nodes"]["std"] for p in POLICIES],
                capsize=6, color=[colors[p] for p in POLICIES])
    axes[1].set_title("Average Active Nodes")
    plt.tight_layout()
    plt.savefig(f"{outdir}/fig6_sla_and_active_nodes.png", dpi=150)
    plt.close()

    # Fig 7 & 8: dynamics over time (trace 0), showing consolidation kicking in
    plt.figure(figsize=(7, 4.2))
    for p in POLICIES:
        plt.plot(range(1, NUM_INTERVALS + 1), series[p][0], marker="o", color=colors[p], label=p)
    plt.xlabel("Simulated interval (10 min each)")
    plt.ylabel("Energy this interval (kWh)")
    plt.title("Energy Over Time (trace 0)")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(f"{outdir}/fig7_energy_over_time.png", dpi=150)
    plt.close()

    plt.figure(figsize=(7, 4.2))
    for p in POLICIES:
        plt.plot(range(1, NUM_INTERVALS + 1), series[p][1], marker="o", color=colors[p], label=p)
    plt.xlabel("Simulated interval (10 min each)")
    plt.ylabel("Active nodes")
    plt.title("Active Nodes Over Time (trace 0) -- watch E3CP consolidate")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(f"{outdir}/fig8_active_nodes_over_time.png", dpi=150)
    plt.close()


def write_report(summary, er, lr, n_traces, n_nodes, path):
    ff, e3 = summary["First-Fit"], summary["E3CP"]
    lines = [
        "E3CP SIMULATION -- SUMMARY REPORT",
        "=" * 40,
        f"Dataset: {n_nodes} heterogeneous edge nodes, {NUM_INTERVALS} intervals x "
        f"{n_traces} independent workload traces.",
        "",
        "Headline result:",
        f"  E3CP reduces modeled energy by {er:.1f}% and average latency by {lr:.1f}% "
        f"relative to First-Fit.",
        f"  E3CP active nodes: {e3['avg_active_nodes']['mean']:.1f} (avg) vs "
        f"{ff['avg_active_nodes']['mean']:.1f} for First-Fit -- consolidation is working.",
        f"  E3CP triggered {e3['migrations']['mean']:.1f} migrations on average per trace; "
        "the other three policies never migrate.",
        "",
        "Reported energy includes modeled node energy plus the fixed migration-energy proxy for accepted migrations.",
        "Network, image-transfer, and sleep/wake-transition energy are not modeled.",
        "Full metric table (mean ± std across traces) is in e3cp_results.csv.",
        "Figures: fig3 (energy bars), fig4 (latency bars), fig5 (trade-off + weight",
        "sensitivity), fig6 (SLA% + active nodes), fig7/fig8 (dynamics over time).",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    nodes_preview = load_nodes()
    summary, series, n_traces = run_all()
    er, lr = print_table(summary, n_traces)
    trace0 = load_requests_by_interval(TRACE_FILES[0])
    sensitivity = run_weight_sensitivity(trace0)
    save_csv(summary, os.path.join(HERE, "e3cp_results.csv"))
    make_plots(summary, series, sensitivity, HERE)
    write_report(summary, er, lr, n_traces, len(nodes_preview), os.path.join(HERE, "report.txt"))
    print(f"\nDataset: {len(nodes_preview)} nodes, {n_traces} workload traces, "
          f"{NUM_INTERVALS} intervals each.")
    print("Saved: e3cp_results.csv, report.txt, fig3-fig8 PNG charts.")
