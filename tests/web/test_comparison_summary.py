"""API presentation summaries are additive and follow evidence filtering."""


def compare(client, **filters):
    return client.post(
        "/api/v1/comparison",
        json={
            "run_ids": ["run-test-exact", "run-test-heuristic"],
            **filters,
        },
    ).json()


def test_summary_uses_authoritative_instance_and_keeps_unpaired_identity(web_env):
    result = compare(web_env["client"])
    instance = result["analysis"]["instances"][0]
    summary = result["instance_summaries"][0]
    assert summary["problem_id"] == instance["problem_id"]
    assert summary["reference_optimum"] == instance["reference_optimum"]
    assert summary["valid_run_count"] == 2
    assert summary["reference_comparable_count"] == 2
    assert summary["optimum_achievement_rate"] is not None
    assert len(summary["groups"]) == 2
    assert not result["analysis"]["comparisons"][0]["pairs"]
    assert set(summary["valid_run_ids"]) == set(result["analysis"]["source_run_ids"])


def test_filter_recomputes_summary_and_does_not_retain_stale_reference(web_env):
    result = compare(web_env["client"], solver="heuristic")
    summary = result["instance_summaries"][0]
    assert summary["reference_optimum"] is None
    assert summary["valid_run_count"] == 1
    assert summary["reference_comparable_count"] == 0
    assert summary["optimum_achievement_rate"] is None
    assert summary["gap_percent"]["mean"] is None
    assert summary["gap_state"] == "unavailable"
    assert summary["groups"][0]["run_ids"] == ["run-test-heuristic"]
    assert result["analysis"]["instances"][0]["runs"][0]["missing_measurements"][
        "optimality_gap_percent"
    ]
    assert compare(web_env["client"], size=999)["instance_summaries"] == []
