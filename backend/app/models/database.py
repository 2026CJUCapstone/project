from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from app.core.database import Base
import uuid
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc)


class Problem(Base):
    __tablename__ = "problems"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    creator_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, index=True, nullable=False)
    difficulty = Column(String, nullable=False) # iron5 ~ diamond1
    tags = Column(JSON, nullable=False)         # ["io", "control", "func"]
    description = Column(Text, nullable=False)
    test_cases = Column(JSON, nullable=False)
    points = Column(Integer, nullable=False, default=100)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now)


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, index=True, nullable=False, unique=True)
    email = Column(String, index=True, nullable=True, unique=True)
    nickname = Column(String, index=True, nullable=True, unique=True)
    hashed_password = Column(String, nullable=False)
    auth_version = Column(Integer, nullable=False, default=0, server_default="0")
    total_score = Column(Integer, nullable=False, default=0)
    avatar_url = Column(String, nullable=True)
    role = Column(String, nullable=False, default="user", index=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class AdminAuditEvent(Base):
    __tablename__ = 'admin_audit_events'
    id = Column(String, primary_key=True, default=lambda:str(uuid.uuid4()))
    request_id = Column(String, nullable=False, index=True)
    actor_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)


class UserProblemScore(Base):
    __tablename__ = "user_problem_scores"
    __table_args__ = (
        UniqueConstraint("user_id", "challenge_id", name="uq_user_problem_scores_user_challenge"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    challenge_id = Column(String, nullable=False, index=True)
    points_awarded = Column(Integer, nullable=False)
    solved_at = Column(DateTime, default=utc_now)


class Submission(Base):
    __tablename__ = "submissions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_job_id = Column(String, ForeignKey('execution_jobs.id'), nullable=True, unique=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    problem_id = Column(String, ForeignKey("problems.id"), nullable=False, index=True)
    language = Column(String, nullable=False)
    code = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    verdict = Column(String, nullable=False, default="system_error", index=True)
    sample_total_cases = Column(Integer, nullable=False, default=0)
    sample_passed_cases = Column(Integer, nullable=False, default=0)
    grading_completed = Column(Boolean, nullable=False, default=False)
    grading_passed = Column(Boolean, nullable=False, default=False)
    awarded_points = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now)


class CompileQueueRecord(Base):
    __tablename__ = "compile_queue_jobs"
    __table_args__ = (Index('ix_compile_queue_history_order', 'status', 'queued_at', 'id'),)
    id = Column(String, primary_key=True)
    kind = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    verdict = Column(String, nullable=False, index=True)
    language = Column(String, nullable=False)
    username = Column(String, nullable=True, index=True)
    user_id = Column(String, nullable=True, index=True)
    problem_id = Column(String, nullable=True, index=True)
    problem_title = Column(String, nullable=True)
    target = Column(String, nullable=True)
    source_size_bytes = Column(Integer, nullable=False, default=0)
    queued_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    wait_ms = Column(Float, nullable=True)
    run_ms = Column(Float, nullable=True)
    error = Column(Text, nullable=True)
    verdict_detail = Column(Text, nullable=True)


class ExecutionQueueLock(Base):
    __tablename__ = "execution_queue_lock"
    id = Column(String, primary_key=True)
    revision = Column(Integer, nullable=False, default=0)


class ExecutionRuntimeRecord(Base):
    """Monotonic incarnation admission fence, not proof of process retirement."""
    __tablename__ = "execution_runtimes"
    id = Column(String, primary_key=True)
    pool_id = Column(String, nullable=False, index=True)
    deployment_sha = Column(String, nullable=False)
    sandbox_pool_id = Column(String, nullable=False)
    registered_at = Column(DateTime, nullable=False, default=utc_now)
    draining_at = Column(DateTime, nullable=True)


class ApiProcessRecord(Base):
    """API process evidence; stopped lifecycle is not container retirement."""
    __tablename__ = 'api_processes'
    id = Column(String, primary_key=True)
    runtime_id = Column(String, ForeignKey('execution_runtimes.id'), nullable=False, index=True)
    pid = Column(Integer, nullable=False)
    start_token = Column(String, nullable=False)
    hostname = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    stopped_at = Column(DateTime, nullable=True)


class ActiveApiRequest(Base):
    """Active-only accounting. No code, URL, credentials or user data."""
    __tablename__ = 'active_api_requests'
    id = Column(String, primary_key=True)
    process_id = Column(String, ForeignKey('api_processes.id'), nullable=False, index=True)
    kind = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False, default=utc_now)


class WorkerProcessRecord(Base):
    """Worker role lifetime, not proof of OS process or container death."""
    __tablename__ = 'worker_processes'
    id = Column(String, primary_key=True)
    runtime_id = Column(String, ForeignKey('execution_runtimes.id'), nullable=False, index=True)
    pid = Column(Integer, nullable=False)
    start_token = Column(String, nullable=False)
    hostname = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    draining_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)


class ExecutionWorkerRecord(Base):
    """Durable claim admission fence, not proof of container retirement."""
    __tablename__ = "execution_workers"
    runtime_id = Column(String, nullable=False, default='', index=True)
    process_id = Column(String, ForeignKey('worker_processes.id'), nullable=True, index=True)
    id = Column(String, primary_key=True)
    pool_id = Column(String, nullable=False, index=True)
    deployment_sha = Column(String, nullable=False)
    sandbox_pool_id = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    draining_at = Column(DateTime, nullable=True)


class ExecutionJob(Base):
    """Private durable worker payload; never serialize through the public queue."""
    __tablename__ = "execution_jobs"
    __table_args__ = (UniqueConstraint("owner_key", "request_id", name="uq_execution_owner_request"),
        Index('ix_execution_content_retention', 'status', 'content_expired_at', 'finished_at'))
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_key = Column(String, nullable=False, index=True)
    quota_key = Column(String, nullable=False, index=True)
    request_id = Column(String, nullable=False)
    payload_hash = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="queued", index=True)
    received_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    lease_token = Column(String, nullable=True)
    lease_until = Column(DateTime, nullable=True, index=True)
    worker_id = Column(String, ForeignKey('execution_workers.id'), nullable=True, index=True)
    # A durable, unresolved Docker mutation is not released by lease expiry.
    sandbox_operation = Column(JSON(none_as_null=True), nullable=True)
    sandbox_daemon_id = Column(String, nullable=True)
    # Minimal receipt remains after content removal; the same key cannot replay.
    content_expired_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)


class CodeProject(Base):
    __tablename__ = "code_projects"
    __table_args__ = (
        UniqueConstraint("user_id", "scope", name="uq_code_projects_user_scope"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    scope = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, default="main")
    language = Column(String, nullable=False, default="bpp")
    code = Column(Text, nullable=False)
    revision = Column(String, nullable=False, default=lambda: uuid.uuid4().hex)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class Comment(Base):
    __tablename__ = "comments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    problem_id = Column(String, ForeignKey("problems.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class Contest(Base):
    __tablename__ = "contests"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    creator_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    starts_at = Column(DateTime, nullable=False, index=True)
    ends_at = Column(DateTime, nullable=False, index=True)
    published = Column(Boolean, nullable=False, default=False)
    finalized_at = Column(DateTime, nullable=True)
    # The database, not Redis, owns the cache generation.  Every scoreboard
    # fact mutation increments this in its enclosing transaction.
    scoreboard_revision = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, default=utc_now, nullable=False)


class ContestProblem(Base):
    __tablename__ = "contest_problems"
    __table_args__ = (UniqueConstraint("contest_id", "problem_id"), UniqueConstraint("contest_id", "position"))
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    contest_id = Column(String, ForeignKey("contests.id"), nullable=False, index=True)
    problem_id = Column(String, ForeignKey("problems.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    points = Column(Integer, nullable=False)
    is_new = Column(Boolean, nullable=False, default=False)
    snapshot = Column(JSON, nullable=False)


class ContestParticipant(Base):
    __tablename__ = "contest_participants"
    __table_args__ = (UniqueConstraint("contest_id", "user_id"),)
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    contest_id = Column(String, ForeignKey("contests.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    joined_at = Column(DateTime, default=utc_now, nullable=False)


class ContestSubmission(Base):
    __tablename__ = "contest_submissions"
    __table_args__ = (UniqueConstraint("contest_id", "user_id", "request_id"),)
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_job_id = Column(String, ForeignKey('execution_jobs.id'), nullable=True, unique=True)
    contest_id = Column(String, ForeignKey("contests.id"), nullable=False, index=True)
    contest_problem_id = Column(String, ForeignKey("contest_problems.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    request_id = Column(String, nullable=False)
    language = Column(String, nullable=False)
    code = Column(Text, nullable=False)
    received_at = Column(DateTime, nullable=False, index=True)
    status = Column(String, nullable=False, default="queued", index=True)
    verdict = Column(String, nullable=False, default="pending")
    finished_at = Column(DateTime, nullable=True)
    lease_token = Column(String, nullable=True)
    lease_until = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
