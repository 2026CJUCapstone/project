from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from app.core.database import Base
import uuid
from datetime import datetime, timezone

class Problem(Base):
    __tablename__ = "problems"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
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
    total_score = Column(Integer, nullable=False, default=0)
    avatar_url = Column(String, nullable=True)
