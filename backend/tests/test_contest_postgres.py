"""Real PostgreSQL transactions; synthetic execution, NOT live worker proof.

Reuse the identical behavioral assertions, opting only this module into PG.
No TEST_POSTGRES_URL means an explicit skip, never SQLite substitution.
"""
import pytest

from tests.test_contests import (
    env,
    test_deadline_idempotency_and_late_judging,
    test_scoring_first_accept_penalties_ties_and_no_duplicate_rewards,
    test_lifespan_recovers_queue_and_repeated_finalization,
    test_practice_judging_racing_contest_award,
    test_predeadline_receipt_waiting_on_finalizer,
)
from tests.test_contest_rejudge import (
    seeded,
    test_v21_additive_initialization_from_physical_legacy_shape_keeps_records,
)
from tests.test_rejudge_apply import (
    test_two_independent_sqlite_sessions_apply_exactly_once as test_two_sessions_apply_exactly_once,
    test_transaction_failure_rolls_back_claims_scores_snapshot_and_audit,
    test_additive_v18_initializer_preserves_applied_audit_and_claims,
)
from tests.test_rejudge_review import (
    test_two_sessions_idempotent_review_and_latest_decision_sequence,
    test_concurrent_rejection_and_apply_have_one_serial_order,
    test_additive_migration_keeps_historical_provenance_unknown,
)

pytestmark = pytest.mark.parametrize('contest_engine', ['postgres'], indirect=True)
