from sqlalchemy import create_engine, inspect, text

from app.core import database


def test_migrate_schema_preserves_legacy_rows_and_is_idempotent(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database, "engine", test_engine)

    try:
        with test_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE users ("
                    "id VARCHAR PRIMARY KEY, username VARCHAR NOT NULL, nickname VARCHAR, "
                    "hashed_password VARCHAR NOT NULL, total_score INTEGER NOT NULL, avatar_url VARCHAR)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE problems ("
                    "id VARCHAR PRIMARY KEY, creator_id VARCHAR NOT NULL, title VARCHAR NOT NULL, "
                    "difficulty VARCHAR NOT NULL, tags TEXT NOT NULL, description TEXT NOT NULL, "
                    "test_cases TEXT NOT NULL, created_at TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE submissions ("
                    "id VARCHAR PRIMARY KEY, user_id VARCHAR, problem_id VARCHAR NOT NULL, "
                    "status VARCHAR NOT NULL, created_at TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE comments ("
                    "id VARCHAR PRIMARY KEY, problem_id VARCHAR NOT NULL, created_at TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE code_projects ("
                    "id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, scope VARCHAR NOT NULL, "
                    "title VARCHAR NOT NULL, language VARCHAR NOT NULL, code TEXT NOT NULL, "
                    "created_at TIMESTAMP, updated_at TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO users (id, username, nickname, hashed_password, total_score, avatar_url) "
                    "VALUES ('user-1', 'legacy-user', 'Legacy', 'hash', 42, 'avatar.png')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO problems (id, creator_id, title, difficulty, tags, description, test_cases, created_at) "
                    "VALUES ('problem-1', 'user-1', 'Legacy problem', 'iron5', '[]', 'old', '[]', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO code_projects (id, user_id, scope, title, language, code, created_at, updated_at) "
                    "VALUES ('project-1', 'user-1', 'ide', 'Legacy project', 'bpp', 'print(1)', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        database.migrate_schema()

        inspector = inspect(test_engine)
        assert "auth_version" in {column["name"] for column in inspector.get_columns("users")}
        assert "deleted_at" in {column["name"] for column in inspector.get_columns("problems")}
        assert "revision" in {column["name"] for column in inspector.get_columns("code_projects")}
        with test_engine.connect() as connection:
            user = connection.execute(
                text("SELECT username, total_score, auth_version FROM users WHERE id = 'user-1'")
            ).one()
            problem = connection.execute(
                text("SELECT title, deleted_at FROM problems WHERE id = 'problem-1'")
            ).one()
            project = connection.execute(
                text("SELECT user_id, scope, code, revision FROM code_projects WHERE id = 'project-1'")
            ).one()
            initial_migration_count = connection.execute(
                text("SELECT COUNT(*) FROM schema_migrations")
            ).scalar_one()

        assert user == ("legacy-user", 42, 0)
        assert problem == ("Legacy problem", None)
        assert project == ("user-1", "ide", "print(1)", "legacy")
        assert initial_migration_count == 4

        database.migrate_schema()

        with test_engine.connect() as connection:
            assert connection.execute(
                text("SELECT username, total_score, auth_version FROM users WHERE id = 'user-1'")
            ).one() == ("legacy-user", 42, 0)
            assert connection.execute(
                text("SELECT title, deleted_at FROM problems WHERE id = 'problem-1'")
            ).one() == ("Legacy problem", None)
            assert connection.execute(
                text("SELECT user_id, scope, code, revision FROM code_projects WHERE id = 'project-1'")
            ).one() == ("user-1", "ide", "print(1)", "legacy")
            assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == initial_migration_count
    finally:
        test_engine.dispose()
