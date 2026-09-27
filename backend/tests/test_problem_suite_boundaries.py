"""Shared problem-authoring and measured-publication test-suite boundaries."""

import pytest

from app.models.judge_test_manifest import MAX_TEST_DATA_BYTES, canonical_suite
from app.models.schemas import ProblemCreate
from app.services.judge_policy import content_hash, test_suite_hash as suite_hash


CASE = {"input": "", "expectedOutput": ""}
BASE = {"title": "Boundary", "description": "Draft", "difficulty": "bronze5"}


@pytest.mark.parametrize("count,accepted", [(0, True), (1, True), (200, True), (201, False)])
def test_problem_create_preserves_empty_draft_and_enforces_case_count(count, accepted):
    payload = {**BASE, "testCases": [CASE] * count}
    if accepted:
        assert len(ProblemCreate.model_validate(payload).test_cases) == count
    else:
        with pytest.raises(ValueError, match="1 to 200"):
            ProblemCreate.model_validate(payload)


def test_hidden_cases_share_total_count_limit_with_public_samples():
    payload = {**BASE, "testCases": [CASE], "hiddenTestCases": [CASE] * 200}
    with pytest.raises(ValueError, match="1 to 200"):
        ProblemCreate.model_validate(payload)


def test_inline_values_use_existing_sixteen_mib_per_value_budget():
    edge = "x" * MAX_TEST_DATA_BYTES
    assert len(canonical_suite([], [{"input": edge, "expectedOutput": ""}])["hidden"]) == 1
    with pytest.raises(ValueError, match="per-value byte budget"):
        ProblemCreate.model_validate({**BASE, "hiddenTestCases": [{"input": edge + "x", "expectedOutput": ""}]})
    with pytest.raises(ValueError, match="per-value byte budget"):
        ProblemCreate.model_validate({**BASE, "testCases": [{"input": "", "expectedOutput": edge + "x"}]})


def test_policy_hash_uses_exact_same_canonical_bounds_without_changing_valid_hash():
    sample = [{"input": "1\r\n", "expectedOutput": "2\n"}]
    hidden = [{"input": "3\n", "expected_output": "4\n"}]
    historical = content_hash({"sample": [{"input": "1\r\n", "expectedOutput": "2\n"}],
                               "hidden": [{"input": "3\n", "expectedOutput": "4\n"}]})
    assert suite_hash(sample, hidden) == historical
    assert suite_hash(sample, hidden) == content_hash(canonical_suite(sample, hidden))
    with pytest.raises(ValueError, match="1 to 200"):
        suite_hash([CASE] * 201, [])
