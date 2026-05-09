from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from app.core.database import Base
import uuid
from datetime import datetime, timezone

class Problem(Base):
    __tablename__ = "problems"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    creator_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, index=True, nullable=False)
    difficulty = Column(String, nullable=False) # beginner, intermediate, advanced
    tags = Column(JSON, nullable=False)         # ["io", "control", "func"]
    description = Column(Text, nullable=False)
    test_cases = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, index=True, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    total_score = Column(Integer, nullable=False, default=0)
    avatar_url = Column(String, nullable=True)


class UserProblemScore(Base):
    __tablename__ = "user_problem_scores"
    __table_args__ = (
        UniqueConstraint("user_id", "challenge_id", name="uq_user_problem_scores_user_challenge"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    challenge_id = Column(String, nullable=False, index=True)
    points_awarded = Column(Integer, nullable=False)
    solved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Comment(Base):
    __tablename__ = "comments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    problem_id = Column(String, ForeignKey("problems.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
