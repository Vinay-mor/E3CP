# E3CP multi-seed simulation report

- Master seeds: 42, 43, 44, 45, 46, 47, 48, 49, 50, 51 (10 total).
- Per seed: 30 heterogeneous nodes, 5 workload traces, 12 ten-minute intervals per trace.
- Total policy-trace runs: 400.
- Each seed generates one fleet shared across its workload traces; policies are evaluated on paired traces.
- Reported standard deviations are across master-seed means and are not confidence intervals.
- Modeled total energy equals modeled awake-node energy plus the fixed migration-energy proxy for accepted container migrations.
- Consolidation is accepted only when the estimated one-interval node-energy saving exceeds the migration-energy proxy; the estimate subtracts destination-node power increases.
- Network energy, image-transfer energy, and sleep/wake-transition energy are not modeled.
- The image metric counts missing image-layer events, not bytes or megabytes.
- SLA failure rate is 100 × (placed requests exceeding estimated latency limits + blocked requests) / all arrived requests.

## Headline descriptive comparison

- E3CP modeled total energy vs First-Fit: 54.93% lower on the across-seed means.
- E3CP estimated placement latency vs First-Fit: 58.95% lower on the across-seed means.
- E3CP mean active nodes: 14.975; First-Fit: 30.000.
- E3CP full vs no-consolidation energy: 1.45891 vs 2.17126 kWh.
- These are synthetic-simulation outcomes and do not establish physical power savings or superiority on real edge hardware.

## Output files

- `results_per_trace.csv`: one row per policy, trace, and master seed.
- `results_by_seed.csv`: per-policy averages over traces within each master seed.
- `results_overall.csv`: means and standard deviations across master-seed means.
- `paired_effects_bootstrap.csv`: paired per-seed differences with percentile bootstrap intervals.
- `fig_energy_multiseed.png`, `fig_latency_multiseed.png`, `fig_sla_multiseed.png`, `fig_active_multiseed.png`, `fig_sla_active_multiseed.png`, `fig_energy_latency_multiseed.png`: figures generated directly from the current results.
