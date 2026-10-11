# E3CP: Energy-Efficient Container Placement for Edge Computing

E3CP is a simulation-based research project for evaluating energy-aware container placement and consolidation policies in a heterogeneous edge-computing environment. It provides a Python simulator, synthetic workload generation, a multi-seed experiment runner, regression tests, and experiment outputs.

> **Scope:** The results come from an analytical simulation using synthetic inputs. They are not measurements from physical edge hardware, and conclusions should be interpreted within the model's assumptions.

## Repository structure

| Path | Purpose |
| --- | --- |
| `e3cp_simulation.py` | Core simulation logic and placement-policy implementations |
| `gen_dataset.py` | Generates seeded synthetic edge-node fleets and workload traces |
| `run_experiments.py` | Runs the multi-seed, eight-policy evaluation and generates result tables, reports, and figures |
| `test_simulation_audit.py` | Regression tests for audited simulation edge cases |
| `requirements.txt` | Python dependencies |
| `experiment_output/` | Current experiment report, aggregate and per-run results, figures, and generated datasets |

## Requirements and setup

Use Python 3.10 or later and install the dependencies listed in `requirements.txt`.

The following commands use Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

## Reproduce the main experiment

### 1. Run regression tests

```bash
python -m unittest -v test_simulation_audit.py
```

### 2. Run the multi-seed evaluation

```bash
python run_experiments.py --seeds 42 43 44 45 46 47 48 49 50 51 --num-traces 5 --num-nodes 30 --output-dir experiment_output
```

This configuration runs **10 master seeds × 5 workload traces per seed × 8 policy variants = 400 policy–trace runs**. For each seed, the five workload traces use the same generated heterogeneous node fleet.

The runner generates per-trace, per-seed, and overall result tables, paired-effect summaries, a report, and multi-seed figures in `experiment_output/`. It also writes the generated datasets used by the simulation. Running the experiment again with the same code, dependencies, and parameters should reproduce the seeded synthetic inputs and corresponding outputs.

Standard deviations shown in the reported summaries are descriptive standard deviations across seed-level means; they are not confidence intervals.

## Reported results

See `experiment_output/REPORT.md` and `experiment_output/results_overall.csv` for the saved experiment results.

The current report lists the following results for E3CP:

| Metric | Mean ± standard deviation |
| --- | ---: |
| Modeled energy | 1.4589 ± 0.0991 kWh |
| Estimated placement latency | 22.18 ± 0.89 ms |
| Request-failure rate | 2.35 ± 0.85% |
| Average powered-on nodes | 14.97 ± 0.85 |

Within this evaluation, **Min-Energy + Consolidation** reports the lowest modeled energy (1.2063 ± 0.0695 kWh). **Latency-Aware without consolidation** reports lower estimated latency (12.13 ± 0.51 ms) and request-failure rate (1.49 ± 0.36%).

These values describe the saved experiment under the tested synthetic workloads and model. They should not be interpreted as evidence that a policy will be best in every edge-computing environment.

## Model and limitations

- **Energy:** an analytical node-power estimate plus a fixed migration-energy proxy for accepted container migrations; it is not a physical power measurement.
- **Latency:** an estimate based on regional distance, utilization congestion, and missing-image-layer penalties; it is not measured end-to-end latency.
- **Request-failure rate:** combines requests that exceed their latency bound with blocked requests, divided by all arrived requests.
- **Image-layer misses:** reported as event counts, not bytes or megabytes.
- **Excluded effects:** network and image-transfer energy, sleep/wake transition energy, migration duration, service interruption, and hardware calibration are not modelled.
- **Synthetic inputs:** node attributes and workload traces are generated synthetically, so findings are limited to the scenarios represented by those inputs.
- **Consolidation:** the simplified controller assumes projected energy savings apply over one subsequent interval and does not predict demand in that interval.

## Implementation notes

The audited simulation includes QoS-aware wake-up checks before the documented fallback is applied, avoids applying the one-interval consolidation heuristic at the final simulation boundary, and aligns powered-on-node and utilization snapshots with the interval used for energy accounting. The regression tests cover the audited wake-up behavior and final-boundary accounting.
