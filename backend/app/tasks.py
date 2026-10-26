"""Durable PostgreSQL task queue: leased claims, renewal, retry with backoff and dead letters."""
from datetime import timedelta
from sqlalchemy import select, update, or_, and_
from sqlalchemy.exc import IntegrityError
from .db import Task, now

LEASE_SECONDS = 300

def enqueue(db, kind, payload, dedupe_key=None, max_attempts=3, delay_seconds=0):
    """Add a task unless an unfinished task with the same dedupe key exists. Caller commits."""
    if dedupe_key and db.scalar(select(Task.id).where(Task.dedupe_key == dedupe_key)): return None
    task = Task(kind=kind, payload=payload, dedupe_key=dedupe_key, max_attempts=max_attempts, run_after=now() + timedelta(seconds=delay_seconds))
    try:
        with db.begin_nested(): db.add(task); db.flush()
    except IntegrityError:
        return None
    return task

def claim(db, owner, kinds=None):
    """Claim one due task. Expired leases (crashed workers) are reclaimable. Commits the claim."""
    current = now()
    query = select(Task).where(or_(and_(Task.status == 'queued', Task.run_after <= current),
                                   and_(Task.status == 'running', Task.lease_expires_at < current)))
    if kinds: query = query.where(Task.kind.in_(kinds))
    task = db.scalar(query.order_by(Task.run_after).limit(1).with_for_update(skip_locked=True))
    if not task: return None
    if task.status == 'running' and task.attempts >= task.max_attempts:
        # Lease expired on the final attempt: the worker died mid-task.
        dead(db, task, 'Worker lease expired on final attempt'); db.commit(); return None
    task.status, task.lease_owner, task.lease_expires_at = 'running', owner, current + timedelta(seconds=LEASE_SECONDS)
    task.attempts += 1
    db.commit()
    return task

def renew(db, task_id, owner):
    """Extend a lease while work continues. Returns False if another worker has taken over."""
    result = db.execute(update(Task).where(Task.id == task_id, Task.lease_owner == owner, Task.status == 'running')
                        .values(lease_expires_at=now() + timedelta(seconds=LEASE_SECONDS)))
    db.commit()
    return result.rowcount == 1

def complete(db, task):
    task.status, task.finished_at, task.dedupe_key, task.lease_owner, task.lease_expires_at = 'done', now(), None, None, None

def dead(db, task, error):
    task.status, task.finished_at, task.dedupe_key, task.last_error = 'dead', now(), None, error[:500]
    task.lease_owner = task.lease_expires_at = None

def fail(db, task, error):
    """Retry with exponential backoff until max_attempts, then move to the dead-letter state."""
    task.last_error = error[:500]
    if task.attempts >= task.max_attempts: return dead(db, task, error)
    task.status, task.lease_owner, task.lease_expires_at = 'queued', None, None
    task.run_after = now() + timedelta(seconds=min(60 * 2 ** (task.attempts - 1), 3600))

def summary(db):
    from sqlalchemy import func
    rows = db.execute(select(Task.kind, Task.status, func.count()).group_by(Task.kind, Task.status)).all()
    return [{'kind': k, 'status': s, 'count': c} for k, s, c in rows]
