"""Public problem selection and private, durable learning progress.

No source code, hidden tests or live contest progress is exposed here.
"""
from sqlalchemy import String, cast, case, func, or_, exists, select
from app.models import database as m
from app.services.contest_access import private_problem_ids, iso, utc_naive
from app.core.bootstrap import SYSTEM_BOARD_IDS
from app.services.public_identity import public_problem_id

DIFFICULTIES = [f"{tier}{level}" for tier in ("iron", "bronze", "silver", "gold", "platinum", "diamond", "ruby") for level in range(5, 0, -1)]
TRACKS = [
    ("io", "입출력부터 시작", "표준 입력을 읽고 정해진 형식으로 출력하는 연습입니다.", ["io"]),
    ("condition", "조건문과 반복문", "조건에 따라 분기하고 같은 작업을 반복해 보세요.", ["condition", "loop", "control"]),
    ("array", "배열과 문자열", "여러 값을 저장하고 문자열을 다루는 연습입니다.", ["array", "string"]),
    ("func", "함수와 수학", "함수로 코드를 나누고 기본적인 수학 문제를 풀어보세요.", ["func", "math"]),
    ("sort", "정렬과 탐색", "값을 정렬하고 원하는 값을 찾는 방법을 익혀보세요.", ["sort", "search"]),
    ("greedy", "구현과 그리디", "조건을 코드로 옮기고 선택 기준을 세우는 연습입니다.", ["implementation", "greedy"]),
    ("graph", "그래프와 동적 계획법", "그래프를 탐색하고 작은 문제의 답을 재사용해 보세요.", ["graph", "dp"]),
]
REVIEW_VERDICTS = ("wrong_answer", "compile_error", "runtime_error", "time_limit_exceeded",
                   "memory_limit_exceeded", "output_limit_exceeded", "process_limit_exceeded",
                   "compile_resource_error")


def insert_for(db):
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def record_attempt(db, submission):
    if not submission.user_id or submission.verdict not in (*REVIEW_VERDICTS, 'accepted'):
        return
    stmt = insert_for(db)(m.ProblemLearningRecord).values(
        user_id=submission.user_id, problem_id=submission.problem_id,
        last_attempt_at=utc_naive(submission.created_at),
        last_submission_id=submission.id, last_verdict=submission.verdict,
        bookmarked=False, note="", version=0)
    excluded = stmt.excluded
    # Reception order, not finish order. Equal timestamps use a stable ID tie break.
    newer = or_(m.ProblemLearningRecord.last_attempt_at.is_(None),
        m.ProblemLearningRecord.last_attempt_at < excluded.last_attempt_at,
        (m.ProblemLearningRecord.last_attempt_at == excluded.last_attempt_at) &
        (m.ProblemLearningRecord.last_submission_id <= excluded.last_submission_id))
    db.execute(stmt.on_conflict_do_update(
        index_elements=["user_id", "problem_id"],
        set_={"last_attempt_at": excluded.last_attempt_at, "last_submission_id": excluded.last_submission_id,
              "last_verdict": excluded.last_verdict}, where=newer))


def backfill_progress(db):
    # Only called by serialized schema initialization, once. Already-pruned history
    # cannot be reconstructed; new progress survives future retention pruning.
    rows = db.query(m.Submission).filter(m.Submission.user_id.is_not(None),
        ~m.Submission.status.in_(["queued", "running"])).order_by(m.Submission.created_at, m.Submission.id)
    for submission in rows.yield_per(200):
        record_attempt(db, submission)


def public_problems(db):
    return db.query(m.Problem).filter(m.Problem.deleted_at.is_(None),
        ~m.Problem.id.in_(SYSTEM_BOARD_IDS),
        ~m.Problem.id.in_(private_problem_ids()))


def difficulty_order():
    return case({value: index for index, value in enumerate(DIFFICULTIES)}, value=m.Problem.difficulty, else_=0)


def for_track(query, track):
    # Tags are controlled identifiers. Matching quoted JSON string values works
    # on SQLite and PostgreSQL without a dialect-specific JSON containment operator.
    return query.filter(or_(*(cast(m.Problem.tags, String).like(f'%"{tag}"%') for tag in track[3])))


def solved_expression(user_id):
    return exists(select(m.UserProblemScore.id).where(m.UserProblemScore.user_id == user_id,
        m.UserProblemScore.challenge_id == m.Problem.id))


def learning_items(db, problems, user_id=None):
    ids = [problem.id for problem in problems]
    if not ids:
        return []
    records = {r.problem_id: r for r in db.query(m.ProblemLearningRecord).filter(
        m.ProblemLearningRecord.user_id == user_id, m.ProblemLearningRecord.problem_id.in_(ids)).all()} if user_id else {}
    solved = {r[0] for r in db.query(m.UserProblemScore.challenge_id).filter(
        m.UserProblemScore.user_id == user_id, m.UserProblemScore.challenge_id.in_(ids)).all()} if user_id else set()
    return [{
        "id": public_problem_id(p), "title": p.title, "difficulty": p.difficulty, "tags": p.tags,
        "solved": p.id in solved,
        "attempted": bool(records.get(p.id) and records[p.id].last_attempt_at),
        "bookmarked": bool(records.get(p.id) and records[p.id].bookmarked),
        "note": records[p.id].note if p.id in records else "",
        "reviewedAt": iso(records[p.id].reviewed_at) if p.id in records else None,
        "lastAttemptAt": iso(records[p.id].last_attempt_at) if p.id in records else None,
    } for p in problems]


def track_summary(db, track, user_id=None):
    query = for_track(public_problems(db), track)
    next_query = query.filter(~solved_expression(user_id)) if user_id else query
    next_problem = next_query.order_by(difficulty_order(), m.Problem.id).first()
    return {"id": track[0], "title": track[1], "description": track[2],
        "order": TRACKS.index(track) + 1, "total": query.count(),
        "solved": query.filter(solved_expression(user_id)).count() if user_id else 0,
        "nextProblemId": public_problem_id(next_problem) if next_problem else None}


def recommendations(db, user_id=None):
    solved = public_problems(db).filter(solved_expression(user_id)).with_entities(
        m.Problem.difficulty, m.Problem.tags).all() if user_id else []
    levels = sorted(DIFFICULTIES.index(p.difficulty) for p in solved if p.difficulty in DIFFICULTIES)
    # Median is robust to a single unusually difficult solve. Move one step up.
    target = min(len(DIFFICULTIES) - 1, levels[len(levels) // 2] + 1) if levels else 0
    query = public_problems(db)
    if user_id:
        query = query.filter(~solved_expression(user_id))
    candidates = query.order_by(func.abs(difficulty_order() - target), difficulty_order(), m.Problem.id).limit(200).all()
    tag_counts = {}
    for p in solved:
        for tag in p.tags or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    items = learning_items(db, candidates, user_id)
    def rank(item):
        distance = abs(DIFFICULTIES.index(item["difficulty"]) - target) if item["difficulty"] in DIFFICULTIES else 30
        weakness = min((tag_counts.get(tag, 0) for tag in item["tags"]), default=0)
        return (distance, weakness, not item["attempted"], item["id"])
    chosen = sorted(items, key=rank)[:6]
    for item in chosen:
        item["reason"] = ("아직 해결하지 못한 문제를 다시 풀어보세요." if item["attempted"] else
            "해결 기록이 적어 입문 난이도부터 추천합니다." if not solved else
            "푼 문제의 난이도와 주제별 해결 수를 기준으로 골랐습니다.")
    return {"items": chosen, "targetDifficulty": DIFFICULTIES[target], "signedIn": bool(user_id)}
