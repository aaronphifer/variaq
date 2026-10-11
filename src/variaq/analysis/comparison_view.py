"""Bounded UI summaries of authoritative per-instance measurements.

This is a derived view, not a replacement for analysis or recorded pairing.
No reference, objective, gap, timing scope or run identity is reinterpreted.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

from variaq.analysis.metrics import make_repeat_summary
from variaq.analysis.paired import TIMING_FIELDS


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _summary(runs: list[dict[str, Any]], optimum: float | None) -> dict[str, Any]:
    valid = [
        r
        for r in runs
        if r["status"] == "success" and r["feasible"] is True and _finite(r["objective"])
    ]
    comparable = [r for r in valid if _finite(r["optimality_gap"])] if _finite(optimum) else []
    achieved = [r for r in comparable if abs(r["objective"] - optimum) <= 1e-9]
    gaps = [r["optimality_gap_percent"] for r in comparable if _finite(r["optimality_gap_percent"])]
    zero = sum(gap == 0 for gap in gaps)
    return {
        "valid_run_count": len(valid),
        "valid_run_ids": [r["run_id"] for r in valid],
        "excluded_run_count": len(runs) - len(valid),
        "reference_comparable_count": len(comparable),
        "reference_comparable_run_ids": [r["run_id"] for r in comparable],
        "optimum_achieved_count": len(achieved),
        "optimum_achievement_rate": len(achieved) / len(comparable) if comparable else None,
        "objective": make_repeat_summary([r["objective"] for r in valid]).to_dict(),
        "gap_percent": make_repeat_summary(gaps).to_dict(),
        "gap_counts": {
            "zero": zero,
            "nonzero": len(gaps) - zero,
            "unavailable": len(runs) - len(gaps),
        },
        "gap_state": "unavailable" if not gaps else "all_zero" if zero == len(gaps) else "nonzero",
        "timing": {
            field: make_repeat_summary([r["timing"][field] for r in valid]).to_dict()
            for field in TIMING_FIELDS
        },
    }


def comparison_view(instances: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    """Keep configurations, executions, precision and timing scopes separate.

    Seeds/candidate angles vary across repeated searches under the same budget;
    their exact values remain in the source measurements. Grouping never implies
    matched controls or pairing. Achievement uses existing quality's 1e-9 rule.
    """
    result = []
    for instance in instances:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        identities = {}
        for run in instance["runs"]:
            backend = {
                k: v
                for k, v in run["backend"].items()
                if k not in {"metrics", "reproducibility_notes"}
            }
            identity = {
                "solver": run["solver"],
                "solver_version": run["solver_version"],
                "backend": backend,
                "parameters": {
                    k: v for k, v in run["parameters"].items() if k != "candidate_parameters"
                },
                "precision": run["precision"],
                "warmup_mode": run["warmup_mode"],
                "timing_scopes": run["timing_scopes"],
                "benchmark_id": run["benchmark_id"],
                "environment": {
                    k: v for k, v in run["environment"].items() if k != "benchmark_protocol"
                },
                "hardware": {
                    k: run["backend"]["metrics"][k]
                    for k in ("gpus", "gpu_count", "target_name", "target_type", "target_options")
                    if k in run["backend"]["metrics"]
                },
            }
            key = json.dumps(identity, sort_keys=True)
            identities[key] = identity
            buckets[key].append(run)
        optimum = instance["reference_optimum"]
        groups = [
            {
                "group_id": f"config-{index + 1}",
                **identities[key],
                "run_ids": [r["run_id"] for r in runs],
                **_summary(runs, optimum),
            }
            for index, (key, runs) in enumerate(sorted(buckets.items()))
        ]
        result.append(
            {
                "problem_id": instance["problem_id"],
                "reference_optimum": optimum,
                **_summary(instance["runs"], optimum),
                "groups": groups,
            }
        )
    return result
