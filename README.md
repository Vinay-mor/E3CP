# E3CP audited simulation release

This package contains the simulation code, regression tests, synthetic inputs, and updated multi-seed experiment outputs. **The manuscript is intentionally not bundled here**: it should be regenerated from these audited outputs and formatted after the target conference/template is chosen.

## Setup (Windows PowerShell)

Open this extracted folder in VS Code, then run in its terminal:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, either follow your institution's policy for script execution or skip activation and run `python -m pip install --user -r requirements.txt`.

## Reproduce the main experiment

```powershell
python -m unittest -v test_simulation_audit.py
python run_experiments.py --seeds 42 43 44 45 46 47 48 49 50 51 --num-traces 5 --num-nodes 30 --output-dir experiment_output
python make_manuscript_figures.py --output-dir experiment_output
```

This is 10 master seeds × 5 workload traces per seed × 8 policy variants = **400 policy–trace runs**. Each seed has one generated heterogeneous node fleet shared by its five traces. The standard deviations shown in the plots are across seed-level means; they are descriptive SDs, not confidence intervals.

The run regenerates `experiment_output/results_per_trace.csv`, `results_by_seed.csv`, `results_overall.csv`, `paired_effects_bootstrap.csv`, `REPORT.md`, figures, and the per-seed dataset folders. Figure 5's combined panel is `experiment_output/fig_sla_active_multiseed.png`.

## Standalone original four-policy experiment

The fixed root-level node/workload CSVs are supplied for the original quick run:

```powershell
python e3cp_simulation.py
```

That runs the four policies on the fixed seed-42 traces. **Do not mix its outputs with the main 10-seed, 8-policy results.** The paper-level experiment is run by `run_experiments.py`.

## Audit fixes included

1. **QoS-aware wake-up:** if no awake node satisfies E3CP's latency/reliability gate, the simulator checks sleeping nodes for a feasible host and wakes a feasible sleeping candidate before applying the documented QoS fallback. The E3CP-no-consolidation variant uses the same placement and wake-up logic.
2. **Final interval:** the one-interval consolidation heuristic is skipped at the final boundary because no subsequent interval exists in which projected savings can accrue. This avoids charging migration overhead for an unevaluated future saving.
3. **Aligned snapshots:** powered-on-node and utilization averages use the same pre-boundary state as the interval's modeled node-energy estimate. Consolidation at an interval boundary affects the following interval.
4. **Fresh combined figure:** the experiment runner directly generates `fig_sla_active_multiseed.png` from the newly computed aggregate results.
5. **Regression tests:** the test suite verifies QoS-aware wake-up for both E3CP variants and final-boundary accounting.

## Metric interpretation and limitations

- **Energy** is an analytical node-power estimate plus a fixed migration-energy proxy for accepted container migrations. It is not measured on physical hardware.
- **Latency** is estimated from regional distance, a utilization congestion term, and missing-image-layer penalty. It is not measured end-to-end latency.
- **Request-failure rate** counts placed requests that exceed their latency bound plus blocked requests, divided by all arrived requests.
- **Image-layer misses** are event counts, not bytes or megabytes.
- Network/image-transfer energy, sleep/wake transition energy, migration duration, service interruption, and hardware calibration are not modelled.
- Workloads and fleet attributes are synthetic. Results demonstrate behavior under this model's assumptions; they do not prove general superiority on real edge systems.
- The simple consolidation controller assumes the expected energy saving applies over one subsequent interval. Demand at the next interval is not predicted.

## Exact audited results

See `experiment_output/REPORT.md` and `experiment_output/results_overall.csv`. The corrected code produces E3CP means of 1.4589 ± 0.0991 kWh modeled energy, 22.18 ± 0.89 ms estimated placement latency, 2.35 ± 0.85% request-failure rate, and 14.97 ± 0.85 average powered-on nodes. Min-Energy + Consolidation has the lowest modeled energy (1.2063 ± 0.0695 kWh), while Latency-Aware without consolidation has lower latency (12.13 ± 0.51 ms) and request-failure rate (1.49 ± 0.36%). These are estimates from synthetic simulation and are not hardware measurements.

## Files

- `e3cp_simulation.py` — core simulation and policy functions
- `run_experiments.py` — 10-seed, eight-policy evaluation and aggregate plots
- `gen_dataset.py` — seeded synthetic fleet and trace generator
- `make_manuscript_figures.py` — creates manuscript-support figures from selected experiment output
- `test_simulation_audit.py` — regression tests for the audited edge cases
- `experiment_output/` — verified results, figures, and generated per-seed datasets

## Manuscript status

The previous DOCX/PDF were not copied into this bundle because their reported values and graphics predate this audit. Once the conference format is selected, regenerate the manuscript tables/figures from `experiment_output/` and apply that venue's template. Do not submit the stale manuscript with these new results.
