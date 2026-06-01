from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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
    created_at = Column(DateTime, default=utc_now)


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, index=True, nullable=False, unique=True)
    email = Column(String, index=True, nullable=True, unique=True)
    nickname = Column(String, index=True, nullable=True, unique=True)
    hashed_password = Column(String, nullable=False)
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
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    problem_id = Column(String, ForeignKey("problems.id"), nullable=False, index=True)
    language = Column(String, nullable=False)
    code = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    sample_total_cases = Column(Integer, nullable=False, default=0)
    sample_passed_cases = Column(Integer, nullable=False, default=0)
    grading_completed = Column(Boolean, nullable=False, default=False)
    grading_passed = Column(Boolean, nullable=False, default=False)
    awarded_points = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now)


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
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class Comment(Base):
    __tablename__ = "comments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    problem_id = Column(String, ForeignKey("problems.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)
