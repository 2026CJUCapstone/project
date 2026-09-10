"""Administrator mutation audit rows commit atomically with the mutation."""
from contextvars import ContextVar
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.database import AdminAuditEvent

audit_context = ContextVar('admin_audit_context', default=None)


class AuditContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        # Never include request body, query string, cookies, tokens, or headers.
        context = {'request_id':str(uuid4()), 'actor_id':None,
                   'action':f"{scope['method']} {scope['path'][:400]}",
                   'mutation':scope['method'] in ('POST','PUT','PATCH','DELETE')}
        token = audit_context.set(context)
        try:
            await self.app(scope, receive, send)
        finally:
            audit_context.reset(token)


def mark_admin(actor_id):
    context = audit_context.get()
    if context is not None:
        # FastAPI dependencies/handlers run in copied thread contexts. Updating
        # this request-local object propagates identity without cross-request state.
        context['actor_id'] = actor_id


@event.listens_for(Session, 'before_commit')
def audit_admin_commit(session):
    context = audit_context.get()
    if not context or not context['mutation'] or not context['actor_id'] or session.in_nested_transaction():
        return
    session.add(AdminAuditEvent(request_id=context['request_id'], actor_id=context['actor_id'], action=context['action']))
