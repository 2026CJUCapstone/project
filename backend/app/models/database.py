from sqlalchemy import Column, String, Text, JSON, DateTime
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
