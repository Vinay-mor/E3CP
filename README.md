# E3CP: Energy-Efficient Container Placement for Edge Computing

E3CP is a simulation-based research project that evaluates container-placement and consolidation policies in a heterogeneous edge-computing environment. The repository contains the simulator, synthetic workload and node-fleet generators, regression tests, experiment scripts, and audited multi-seed results.

> **Research scope:** Results are produced by an analytical simulation using synthetic inputs. They should be interpreted within the model's assumptions, not as measurements from physical edge hardware.

## Overview

The experiments compare eight policy variants across multiple seeds and workload traces, examining modeled energy consumption, estimated placement latency, request-failure rate, and the number of powered-on nodes. The evaluation is designed to make the experiment reproducible and to expose trade-offs between energy efficiency and service quality.

## Repository structure

| File or directory | Purpose |
| --- | --- |
| `e3cp_simulation.py` | Core simulator and original four-policy experiment |
| `gen_dataset.py` | Generates seeded synthetic node fleets and workload traces |
| `run_experiments.py` | Runs the multi-seed, eight-policy evaluation and produces aggregate results |
| `test_simulation_audit.py` | Regression tests for audited simulation edge cases |
| `experiment_output/` | Experiment reports, result tables, figures, and per-seed datasets |
| `make_manuscript_figures.py` | Optional utility for regenerating manuscript-support figures from experiment outputs |

## Requirements and setup

The commands below use Windows PowerShell. Open the repository folder in a terminal and create a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If activation is blocked by your environment's execution policy, follow your institution's or administrator's guidance. You can also install the dependencies without activating the environment:

```powershell
python -m pip install --user -r requirements.txt
```

## Reproduce the main experiment

### 1. Run the regression tests

```powershell
python -m unittest -v test_simulation_audit.py
```

### 2. Run the multi-seed evaluation

```powershell
python run_experiments.py --seeds 42 43 44 45 46 47 48 49 50 51 --num-traces 5 --num-nodes 30 --output-dir experiment_output
```

This configuration uses **10 master seeds × 5 workload traces per seed × 8 policy variants = 400 policy–trace runs**. For each seed, the five traces share the same generated heterogeneous node fleet.

The experiment runner generates per-trace, per-seed, and overall result tables, paired-effect summaries, a report, and the six current multi-seed figures under `experiment_output/`. It also creates per-seed datasets used by the simulation. Standard deviations in the plots are calculated across seed-level means; they are descriptive standard deviations, not confidence intervals.

The experiment runner generates the current multi-seed figures directly, including `experiment_output/fig_sla_active_multiseed.png`; no separate figure-generation script is required.

## Audit and reproducibility notes

The audited release includes the following changes and checks:

1. **QoS-aware wake-up:** when no awake node satisfies E3CP's latency/reliability gate, sleeping nodes are checked for a feasible host before the documented QoS fallback is applied. The E3CP variant without consolidation uses the same placement and wake-up logic.
2. **Final-interval accounting:** the one-interval consolidation heuristic is skipped at the final boundary because there is no following interval in which projected savings could accrue.
3. **Aligned metric snapshots:** powered-on-node and utilization averages use the same pre-boundary state as the interval's modeled node-energy estimate. Consolidation at a boundary affects the following interval.
4. **Updated combined figure:** the experiment runner generates `fig_sla_active_multiseed.png` from the newly computed aggregate results.
5. **Regression coverage:** tests check QoS-aware wake-up for both E3CP variants and final-boundary accounting.

## Latest audited results

The detailed results are available in `experiment_output/REPORT.md` and `experiment_output/results_overall.csv`.

For E3CP, the audited experiment reports:

| Metric | Mean ± standard deviation |
| --- | ---: |
| Modeled energy | 1.4589 ± 0.0991 kWh |
| Estimated placement latency | 22.18 ± 0.89 ms |
| Request-failure rate | 2.35 ± 0.85% |
| Average powered-on nodes | 14.97 ± 0.85 |

In this evaluation, **Min-Energy + Consolidation** has the lowest modeled energy (1.2063 ± 0.0695 kWh), while **Latency-Aware without consolidation** has lower estimated latency (12.13 ± 0.51 ms) and request-failure rate (1.49 ± 0.36%). These results describe the tested synthetic workloads and model; they do not establish that one policy is universally superior.

## Metrics and limitations

- **Energy:** analytical node-power estimate plus a fixed migration-energy proxy for accepted container migrations; not measured on physical hardware.
- **Latency:** estimate based on regional distance, utilization congestion, and missing-image-layer penalties; not measured end-to-end latency.
- **Request-failure rate:** requests that exceed their latency bound plus blocked requests, divided by all arrived requests.
- **Image-layer misses:** event counts, not bytes or megabytes.
- **Not modelled:** network/image-transfer energy, sleep/wake transition energy, migration duration, service interruption, and hardware calibration.
- **Synthetic inputs:** workload traces and fleet attributes are generated synthetically. Conclusions are limited to the model assumptions and evaluated scenarios.
- **Consolidation assumption:** the simple controller assumes projected energy savings apply over one subsequent interval and does not predict demand in that interval.
