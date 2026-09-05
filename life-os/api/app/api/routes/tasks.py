"""Todos, work items and projects."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.tasks import OPEN_STATUSES, Project, Task, TaskStatus
from app.models.user import User
from app.schemas.core import ProjectIn, ProjectOut, TaskIn, TaskOut, TaskUpdate

router = APIRouter(tags=["tasks"])


def _owned_task(db: Session, user: User, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    area: str | None = None,
    project_id: str | None = None,
    open_only: bool = True,
    due_within_days: int | None = None,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Task).where(Task.user_id == user.id)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    elif open_only:
        stmt = stmt.where(Task.status.in_([s.value for s in OPEN_STATUSES]))
    if area:
        stmt = stmt.where(Task.area == area)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if due_within_days is not None:
        horizon = datetime.now(timezone.utc) + timedelta(days=due_within_days)
        stmt = stmt.where(Task.due_at.is_not(None), Task.due_at <= horizon)

    return db.scalars(
        stmt.order_by(
            # Dated work first, then by priority — the order you'd actually work.
            Task.due_at.is_(None),
            Task.due_at,
            Task.priority,
        ).limit(limit)
    ).all()


@router.get("/tasks/today", response_model=list[TaskOut])
def today(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Overdue, due today, or flagged P1 — the short list worth looking at."""
    end_of_day = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59)
    return db.scalars(
        select(Task)
        .where(
            Task.user_id == user.id,
            Task.status.in_([s.value for s in OPEN_STATUSES]),
            or_(Task.due_at <= end_of_day, Task.priority == 1),
        )
        .order_by(Task.due_at.is_(None), Task.due_at, Task.priority)
        .limit(25)
    ).all()


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    task = Task(user_id=user.id, **payload.model_dump())
    db.add(task)
    db.commit()
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = _owned_task(db, user, task_id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(task, key, value)
    if "status" in values:
        task.completed_at = (
            datetime.now(timezone.utc) if TaskStatus(task.status) == TaskStatus.done else None
        )
    db.commit()
    return task


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_owned_task(db, user, task_id))
    db.commit()


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(
        select(Project).where(Project.user_id == user.id, Project.is_archived.is_(False))
    ).all()


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    project = Project(user_id=user.id, **payload.model_dump())
    db.add(project)
    db.commit()
    return project
