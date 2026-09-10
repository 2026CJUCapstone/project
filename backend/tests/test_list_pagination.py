from datetime import datetime, timedelta

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.contests import list_contests, problem_library
from app.api.routes.problems import list_problems
from app.core.database import Base
from app.models import database as m


def test_problem_filters_are_counted_before_database_pagination(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'lists.db').as_posix()}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        admin = m.User(id="admin", username="admin-pages", hashed_password="unused", role="admin")
        db.add(admin)
        for index, tags in enumerate((["io"], ["func"], ["io", "func"], ["io"]), start=1):
            db.add(m.Problem(id=f"p{index}", creator_id=admin.id, title=f"Problem {index}",
                             difficulty="iron5", tags=tags, description="x", test_cases=[], points=100))
        db.add_all([
            m.Problem(id="literal", creator_id=admin.id, title="Literal", difficulty="iron5", tags=["100%"], description="x", test_cases=[], points=100),
            m.Problem(id="wildcard", creator_id=admin.id, title="Wildcard", difficulty="iron5", tags=["100x"], description="x", test_cases=[], points=100),
        ])
        db.commit()

        response = Response()
        page = list_problems(response, difficulty=None, tag=["io"], difficulty_min=None, difficulty_max=None,
                             search=None, limit=2, offset=1, db=db, current_user=None)

        assert response.headers["X-Total-Count"] == "3"
        assert [problem["id"] for problem in page] == ["p3", "p4"]

        literal_response = Response()
        literal_page = list_problems(literal_response, difficulty=None, tag=["100%"], difficulty_min=None,
                                     difficulty_max=None, search=None, limit=10, offset=0, db=db, current_user=None)
        assert literal_response.headers["X-Total-Count"] == "1"
        assert [problem["id"] for problem in literal_page] == ["literal"]
    engine.dispose()


def test_contest_and_admin_library_pages_expose_filtered_totals(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'contest-lists.db').as_posix()}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        admin = m.User(id="admin", username="admin-lists", hashed_password="unused", role="admin")
        db.add(admin)
        start = datetime(2030, 1, 1)
        for index in range(3):
            db.add(m.Contest(id=f"c{index}", creator_id=admin.id, title=f"Contest {index}", description="x",
                             starts_at=start + timedelta(days=index), ends_at=start + timedelta(days=index, hours=1),
                             published=index != 0))
            db.add(m.Problem(id=f"p{index}", creator_id=admin.id, title=f"Problem {index}", difficulty="iron5",
                             tags=[], description="x", test_cases=[], points=100))
        db.commit()

        contest_response = Response()
        contests = list_contests(contest_response, limit=1, offset=1, state=None, search=None, db=db, user=None)
        assert contest_response.headers["X-Total-Count"] == "2"
        assert len(contests) == 1

        library_response = Response()
        library = problem_library(library_response, limit=2, offset=1, db=db, user=admin)
        assert library_response.headers["X-Total-Count"] == "3"
        assert [problem["id"] for problem in library] == ["p1", "p2"]
    engine.dispose()
