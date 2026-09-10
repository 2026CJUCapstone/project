from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core import bootstrap
from app.core.database import Base
from app.core.config import settings
from app.models import database as db_models
from app.services import auth


def test_bootstrap_flushes_system_boards_before_community_guide_and_is_idempotent(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bootstrap.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    monkeypatch.setattr(settings, "ADMIN_USERNAME", "bootstrap-admin")
    monkeypatch.setattr(settings, "ADMIN_NICKNAME", "Bootstrap Admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "bootstrap-test-password")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    try:
        with Session() as db:
            existing_user = db_models.User(
                id="existing-user",
                username="existing-user",
                nickname="Existing User",
                hashed_password="existing-hash",
            )
            db.add(existing_user)
            db.flush()
            db.add(
                db_models.Problem(
                    id="existing-problem",
                    creator_id=existing_user.id,
                    title="Existing problem",
                    difficulty="iron5",
                    tags=["io"],
                    description="Existing description",
                    test_cases={"sample": [], "hidden": []},
                )
            )
            db.commit()

            bootstrap.bootstrap_application_data(db)
            bootstrap.bootstrap_application_data(db)

            assert db.get(db_models.User, "existing-user").username == "existing-user"
            assert db.get(db_models.Problem, "existing-problem").title == "Existing problem"
            assert db.query(db_models.User).count() == 2
            assert db.query(db_models.Problem).count() == 3
            assert db.query(db_models.Comment).count() == 1
            assert db.query(db_models.Problem).filter(
                db_models.Problem.id.in_(bootstrap.SYSTEM_BOARD_IDS)
            ).count() == 2
            assert db.query(db_models.Comment).filter(
                db_models.Comment.id == bootstrap.COMMUNITY_GUIDE_NOTICE_ID
            ).count() == 1
    finally:
        engine.dispose()


def test_existing_admin_password_is_not_reinitialized_from_environment(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'admin.db').as_posix()}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "existing-admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "environment-password")

    try:
        with Session() as db:
            db.add(
                db_models.User(
                    username="existing-admin",
                    hashed_password=auth.get_password_hash("chosen-password"),
                    auth_version=7,
                )
            )
            db.commit()

            admin = bootstrap.ensure_admin_user(db)
            db.commit()

            assert auth.verify_password("chosen-password", admin.hashed_password)
            assert not auth.verify_password("environment-password", admin.hashed_password)
            assert admin.auth_version == 7
    finally:
        engine.dispose()


def test_legacy_default_admin_password_is_replaced_and_revokes_prior_token_version(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-admin.db').as_posix()}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "legacy-admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "environment-password")

    try:
        with Session() as db:
            db.add(
                db_models.User(
                    username="legacy-admin",
                    hashed_password=auth.get_password_hash("admin1234"),
                    auth_version=4,
                )
            )
            db.commit()

            admin = bootstrap.ensure_admin_user(db)
            db.commit()

            assert auth.verify_password("environment-password", admin.hashed_password)
            assert not auth.verify_password("admin1234", admin.hashed_password)
            assert admin.auth_version == 5
    finally:
        engine.dispose()
