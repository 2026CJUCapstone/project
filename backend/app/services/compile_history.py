"""Read-only, access-scoped metadata projection for compilation history.

Contest sources/results stay private. Never load ExecutionJob.payload/result or
ContestSubmission.code into this projection, even for administrators.
"""
from sqlalchemy import String, case, cast, func, literal, null, or_, select, union_all

from app.models import database as m
from app.services.contest_access import now_utc, private_problem_ids

OPTION_LIMIT = 200


def visible_history(viewer_id: str | None):
    q, s, p, c = m.CompileQueueRecord, m.ContestSubmission, m.ContestProblem, m.Contest
    at = now_utc()
    fields = [column.name for column in q.__table__.columns]
    public = select(
        *(getattr(q, name).label(name) for name in fields),
        case((q.problem_id.is_(None), literal('ide')), else_=literal('practice')).label('source'),
        cast(null(), String).label('contest_id'),
        cast(null(), String).label('contest_title'),
        cast(null(), String).label('contest_problem_id'),
    ).where(
        or_(q.problem_id.is_(None), q.problem_id.not_in(private_problem_ids(at))),
        # A misplaced old observation must not publish a contest attempt.
        q.id.not_in(select(s.execution_job_id).where(s.execution_job_id.is_not(None))),
    )
    if not viewer_id:
        return public.subquery('visible_history')

    values = {
        'id': literal('contest:') + s.id,
        'kind': literal('grading'), 'status': s.status, 'verdict': s.verdict,
        'language': s.language, 'username': m.User.username, 'user_id': s.user_id,
        'problem_id': p.problem_id,
        'problem_title': func.coalesce(p.snapshot['title'].as_string(), p.problem_id),
        'queued_at': s.received_at, 'finished_at': s.finished_at,
    }
    # All unknown metrics are NULL, not an invented zero. Only title is read
    # from the immutable snapshot, never its statements or hidden test arrays.
    private = select(
        *(values.get(name, cast(null(), q.__table__.c[name].type)).label(name) for name in fields),
        literal('contest').label('source'), c.id.label('contest_id'),
        c.title.label('contest_title'), p.id.label('contest_problem_id'),
    ).select_from(s).join(p, (p.id == s.contest_problem_id) & (p.contest_id == s.contest_id)) \
        .join(c, c.id == s.contest_id).join(m.User, m.User.id == s.user_id).where(
            s.user_id == viewer_id, c.published.is_(True), c.starts_at <= at,
            or_(c.ends_at <= at, select(m.ContestParticipant.id).where(
                m.ContestParticipant.contest_id == c.id,
                m.ContestParticipant.user_id == viewer_id,
            ).exists()),
        )
    return union_all(public, private).subquery('visible_history')


def _groups(rows: list[dict], by: str):
    groups = {}
    for row in rows:
        if by == 'problem':
            key = (f"contest:{row['contest_id']}:{row['contest_problem_id']}"
                   if row['contest_id'] else row['problem_id'] or '__main__')
            identity = {name: row[name] for name in (
                'problem_id', 'problem_title', 'contest_id', 'contest_title', 'contest_problem_id')}
            identity.update(username=None, user_id=None)
            label = row['problem_title'] or row['problem_id'] or '일반 IDE'
        else:
            key = row['user_id'] or row['username'] or '__anonymous__'
            identity = {'username': row['username'], 'user_id': row['user_id']}
            label = row['username'] or '익명'
        group = groups.setdefault(key, dict(
            key=key, label=label, **identity, total=0, queued=0, running=0,
            completed=0, failed=0, canceled=0, verdicts={}, last_queued_at=row['queued_at'],
        ))
        group['total'] += 1
        group[row['status']] += 1
        group['verdicts'][row['verdict']] = group['verdicts'].get(row['verdict'], 0) + 1
        group['last_queued_at'] = max(group['last_queued_at'], row['queued_at'])
    return sorted(groups.values(), key=lambda group: (
        -(group['queued'] + group['running']), -group['total'], group['label'], group['key']))


def history_snapshot(db, *, history_limit: int, viewer_id=None, limit=100, offset=0,
                     status=None, verdict=None, kind=None, username=None,
                     user_id=None, problem_id=None, source=None, contest_id=None,
                     problem_search=None, language=None, mine=False):
    history = visible_history(viewer_id)
    c = history.c
    base = db.query(history)
    scope = base
    if source and source != 'all':
        scope = scope.filter(c.source == source)
    if mine:
        scope = scope.filter(c.user_id == viewer_id) if viewer_id else scope.filter(literal(False))
    if username and username.strip():
        scope = scope.filter(func.lower(c.username) == username.strip().lower())
    if user_id:
        scope = scope.filter(c.user_id == user_id)

    # Facets use authorized metadata only and are bounded independently of the
    # result page. Problem/title search still searches the complete SQL scope.
    contest_rows = scope.with_entities(c.contest_id, c.contest_title).filter(
        c.contest_id.is_not(None)).distinct().order_by(c.contest_title, c.contest_id).limit(OPTION_LIMIT + 1).all()
    if contest_id:
        scope = scope.filter(c.contest_id == contest_id)
    problem_rows = scope.with_entities(c.problem_id, c.problem_title, c.contest_id).filter(
        c.problem_id.is_not(None)).distinct().order_by(
            c.problem_title, c.problem_id, c.contest_id).limit(OPTION_LIMIT + 1).all()

    filtered = scope
    for name, value in (('status', status), ('verdict', verdict), ('kind', kind), ('language', language)):
        if value and value.strip() and value != 'all':
            filtered = filtered.filter(c[name] == value.strip().lower())
    if problem_id:
        filtered = filtered.filter(c.problem_id == problem_id)
    if problem_search and problem_search.strip():
        term = problem_search.strip().lower()
        # Treat % and _ literally, not as wildcard operators.
        filtered = filtered.filter(or_(func.lower(c.problem_title).contains(term, autoescape=True),
                                       func.lower(c.problem_id).contains(term, autoescape=True)))

    positions = {row.id: index for index, row in enumerate(
        base.with_entities(c.id).filter(c.status == 'queued').order_by(c.queued_at, c.id).all(), 1)}
    ordered = filtered.order_by(c.queued_at.desc(), c.id.desc())
    jobs = [dict(row._mapping) for row in ordered.offset(max(0, offset)).limit(limit).all()]
    for job in jobs:
        job['position'] = positions.get(job['id'])
    group_rows = [dict(row._mapping) for row in ordered.limit(history_limit).all()]
    return {
        'jobs': jobs, 'total': base.count(), 'filtered_total': filtered.count(),
        'queued': base.filter(c.status == 'queued').count(),
        'running': base.filter(c.status == 'running').count(),
        'problem_groups': _groups(group_rows, 'problem'),
        'user_groups': _groups(group_rows, 'user'),
        'contest_options': [{'id': row.contest_id, 'title': row.contest_title}
                            for row in contest_rows[:OPTION_LIMIT]],
        'problem_options': [{'id': row.problem_id, 'title': row.problem_title or row.problem_id,
                             'contest_id': row.contest_id} for row in problem_rows[:OPTION_LIMIT]],
        'option_limit': OPTION_LIMIT,
        'options_truncated': len(contest_rows) > OPTION_LIMIT or len(problem_rows) > OPTION_LIMIT,
    }
