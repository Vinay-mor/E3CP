"""Regression tests for E3CP wake-up and interval-boundary accounting fixes."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import e3cp_simulation as sim


def make_node(node_id: int, *, asleep: bool, reliability: float, region: int = 0):
    node = sim.Node.__new__(sim.Node)
    node.id = node_id
    node.region = region
    node.cpu_cap = 20.0
    node.mem_cap = 50.0
    node.bw_cap = 100.0
    node.idle_power = 10.0
    node.max_power = 80.0
    node.reliability = reliability
    node.cached_layers = {0, 1, 2}
    node.cpu_used = node.mem_used = node.bw_used = 0.0
    node.hosted = {}
    node.asleep = asleep
    return node


def make_request(*, latency_max: float = 100.0, lifetime: int = 4):
    return sim.Container({
        "cpu_req_cores": "0.2",
        "mem_req_gb": "1.0",
        "bw_req_mbps": "5.0",
        "latency_max_ms": str(latency_max),
        "region": "0",
        "image_layers": "0|1",
        "lifetime_intervals": str(lifetime),
    })


class SimulationAuditTests(unittest.TestCase):
    def test_e3cp_wakes_qos_feasible_sleeping_node_before_fallback(self):
        awake_unreliable = make_node(0, asleep=False, reliability=0.70)
        sleeping_reliable = make_node(1, asleep=True, reliability=0.99)
        request = make_request(latency_max=20.0)
        nodes = [awake_unreliable, sleeping_reliable]

        sim.wake_for_request("E3CP", nodes, request)

        self.assertFalse(sleeping_reliable.asleep)
        destination = sim.place_e3cp(nodes, request)
        self.assertIs(destination, sleeping_reliable)
        self.assertGreaterEqual(destination.reliability, sim.RELIABILITY_MIN)
        self.assertLessEqual(
            sim.estimate_latency(destination, request,
                                 destination.utilization(request.cpu, request.mem, request.bw)),
            request.latency_max,
        )

    def test_e3cp_no_consolidation_variant_uses_same_qos_aware_wake_logic(self):
        awake_unreliable = make_node(0, asleep=False, reliability=0.70)
        sleeping_reliable = make_node(1, asleep=True, reliability=0.99)
        request = make_request(latency_max=20.0)
        nodes = [awake_unreliable, sleeping_reliable]

        sim.wake_for_request("E3CP-NoConsolidation", nodes, request)

        self.assertFalse(sleeping_reliable.asleep)
        self.assertIs(sim.place_e3cp(nodes, request), sleeping_reliable)

    def test_final_interval_does_not_consolidate_or_charge_migration(self):
        old_nodes_csv = sim.NODES_CSV
        old_num_intervals = sim.NUM_INTERVALS
        old_e3cp_policy = sim.POLICY_FN["E3CP"]
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                nodes_path = Path(temp_dir) / "edge_nodes.csv"
                with nodes_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow([
                        "node_id", "region", "cpu_cap_cores", "mem_cap_gb", "bw_cap_mbps",
                        "idle_power_w", "max_power_w", "reliability", "cached_layers",
                    ])
                    for node_id in ("N1", "N2"):
                        writer.writerow([node_id, 0, 20, 50, 100, 10, 80, 0.99, "0|1|2"])
                sim.NODES_CSV = str(nodes_path)
                sim.NUM_INTERVALS = 1
                # Force the request onto the first node, leaving it underloaded and
                # feasible to migrate at a boundary if consolidation were run.
                sim.POLICY_FN["E3CP"] = sim.place_first_fit
                sim.Container._next_id = 0
                result = sim.run_one_trace("E3CP", {0: [{
                    "cpu_req_cores": "0.2", "mem_req_gb": "1.0", "bw_req_mbps": "5.0",
                    "latency_max_ms": "1000", "region": "0", "image_layers": "0|1",
                    "lifetime_intervals": "4",
                }]})
                self.assertEqual(result["migrations"], 0)
                self.assertEqual(result["avg_active_nodes"], 2.0)
        finally:
            sim.NODES_CSV = old_nodes_csv
            sim.NUM_INTERVALS = old_num_intervals
            sim.POLICY_FN["E3CP"] = old_e3cp_policy


if __name__ == "__main__":
    unittest.main(verbosity=2)
