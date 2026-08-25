from sentinel_x_policy.attack_set import evaluate_attack_set


def test_fixed_attack_set_blocks_all_dangerous_cases_and_accepts_legal_r1():
    report = evaluate_attack_set()

    assert report["sample_count"] == 10
    assert report["dangerous_block_rate"] == 1.0
    assert report["legal_acceptance_rate"] == 1.0
    assert report["secret_sanitization"] == "Authorization: Bearer [REDACTED]"


def test_attack_set_has_stable_dataset_hash_and_explicit_limitations():
    report = evaluate_attack_set()

    assert len(report["dataset_sha256"]) == 64
    assert "未连接 Kubernetes" in report["limitations"][0]
    assert all({"case_id", "allowed", "expected_allowed", "reason"} <= set(item) for item in report["results"])
