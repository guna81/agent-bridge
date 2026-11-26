"""Admin API routes for AgentBridge Captain: Projects, Missions, Tasks, and SSE streams."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..captain.bus import NotificationEvent
from ..captain.orchestrator import serialize_message, serialize_mission, serialize_task
from ..captain.worktree import GitError, get_worktree_diff, remove_worktree, validate_git_repo
from ..db import session_scope
from ..errors import ProxyError
from ..models import Mission, MissionMessage, MissionTask, Project, Provider, iso_utc, utcnow
from .deps import require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    slug = SLUG_RE.sub("-", name.lower()).strip("-")[:48]
    return slug or "project"


def _project_out(p: Project, active_missions: int = 0, total_missions: int = 0) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "repo_path": p.repo_path,
        "base_branch": p.base_branch,
        "captain_provider": p.captain_provider,
        "captain_model": p.captain_model,
        "approval_mode": p.approval_mode,
        "allowed_providers": p.allowed_providers or [],
        "agent_roles": p.agent_roles or {},
        "instructions": p.instructions,
        "max_budget_usd": p.max_budget_usd,
        "webhook_url": p.webhook_url,
        "webhook_events": p.webhook_events or [],
        "active_missions": active_missions,
        "total_missions": total_missions,
        "created_at": iso_utc(p.created_at),
        "updated_at": iso_utc(p.updated_at),
    }


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    repo_path: str = Field(min_length=1, max_length=1024)
    base_branch: str | None = None
    captain_provider: str = ""
    captain_model: str = ""
    approval_mode: str = Field("manual", pattern="^(manual|auto)$")
    allowed_providers: list[str] = Field(default_factory=list)
    agent_roles: dict[str, str] = Field(default_factory=dict)
    instructions: str = ""
    max_budget_usd: float | None = Field(None, gt=0)
    webhook_url: str = ""
    webhook_events: list[str] = Field(default_factory=lambda: ["awaiting_approval", "needs_input", "completed", "failed"])


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    base_branch: str | None = None
    captain_provider: str | None = None
    captain_model: str | None = None
    approval_mode: str | None = Field(None, pattern="^(manual|auto)$")
    allowed_providers: list[str] | None = None
    agent_roles: dict[str, str] | None = None
    instructions: str | None = None
    max_budget_usd: float | None = Field(None, gt=0)
    webhook_url: str | None = None
    webhook_events: list[str] | None = None


@router.get("/projects")
async def list_projects():
    with session_scope() as s:
        projects = list(s.scalars(select(Project).order_by(Project.updated_at.desc(), Project.id.desc())))
        active_counts = dict(
            s.execute(
                select(Mission.project_id, func.count(Mission.id))
                .where(Mission.status.in_(("planning", "awaiting_approval", "running", "needs_input")))
                .group_by(Mission.project_id)
            ).all()
        )
        total_counts = dict(
            s.execute(select(Mission.project_id, func.count(Mission.id)).group_by(Mission.project_id)).all()
        )
        return [
            _project_out(p, active_missions=int(active_counts.get(p.id, 0)), total_missions=int(total_counts.get(p.id, 0)))
            for p in projects
        ]


@router.post("/projects")
async def create_project(body: ProjectCreate):
    try:
        repo_info = await validate_git_repo(Path(body.repo_path))
    except GitError as exc:
        raise ProxyError(400, str(exc), code="invalid_repo") from None

    base_slug = _slugify(body.name)
    with session_scope() as s:
        slug = base_slug
        n = 2
        while s.scalar(select(Project).where(Project.slug == slug)):
            slug = f"{base_slug}-{n}"
            n += 1
        p = Project(
            name=body.name.strip(),
            slug=slug,
            repo_path=repo_info["repo_path"],
            base_branch=(body.base_branch or repo_info["base_branch"]).strip(),
            captain_provider=body.captain_provider.strip(),
            captain_model=body.captain_model.strip(),
            approval_mode=body.approval_mode,
            allowed_providers=body.allowed_providers,
            agent_roles=body.agent_roles,
            instructions=body.instructions,
            max_budget_usd=body.max_budget_usd,
            webhook_url=body.webhook_url.strip(),
            webhook_events=body.webhook_events,
        )
        s.add(p)
        s.flush()
        return _project_out(p)


@router.patch("/projects/{project_id}")
async def update_project(project_id: int, body: ProjectPatch):
    data = body.model_dump(exclude_unset=True)
    with session_scope() as s:
        p = s.get(Project, project_id)
        if not p:
            raise ProxyError(404, "Project not found.", code="not_found")
        for k, v in data.items():
            if isinstance(v, str) and k in ("name", "base_branch", "captain_provider", "captain_model", "webhook_url"):
                v = v.strip()
            setattr(p, k, v)
        p.updated_at = utcnow()
        s.flush()
        return _project_out(p)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, cleanup_worktrees: bool = Query(False)):
    worktrees: list[tuple[Path, Path, str]] = []
    with session_scope() as s:
        p = s.get(Project, project_id)
        if not p:
            raise ProxyError(404, "Project not found.", code="not_found")
        if cleanup_worktrees:
            m_ids = [m.id for m in s.scalars(select(Mission).where(Mission.project_id == project_id))]
            if m_ids:
                for t in s.scalars(select(MissionTask).where(MissionTask.mission_id.in_(m_ids))):
                    if t.worktree_path:
                        worktrees.append((Path(p.repo_path), Path(t.worktree_path), t.branch_name))
        s.delete(p)
    for repo_path, wt_path, branch in worktrees:
        await remove_worktree(repo_path, wt_path, branch_name=branch, delete_branch=False)
    return {"deleted": project_id}


class TestWebhookBody(BaseModel):
    webhook_url: str | None = None


@router.post("/projects/{project_id}/test-webhook")
async def test_project_webhook(project_id: int, body: TestWebhookBody, request: Request):
    with session_scope() as s:
        p = s.get(Project, project_id)
        if not p:
            raise ProxyError(404, "Project not found.", code="not_found")
        url = (body.webhook_url if body.webhook_url is not None else p.webhook_url).strip()
        project_name = p.name
    if not url:
        raise ProxyError(400, "No webhook URL configured for this project.", code="invalid_request")
    notif = NotificationEvent(
        id=0,
        kind="info",
        project_id=project_id,
        project_name=project_name,
        mission_id="test",
        task_id=None,
        title="Test notification from AgentBridge Captain",
        body=f"Webhook delivery for project '{project_name}' is working.",
        created_at=iso_utc(utcnow()) or "",
    )
    try:
        status_code = await request.app.state.captain_channels.deliver_webhook(url, notif)
    except Exception as exc:
        raise ProxyError(400, f"Webhook delivery failed: {exc}", code="webhook_failed") from None
    return {"ok": True, "status_code": status_code}


# ---------- Missions & Tasks ---------------------------------------------------------------------

class MissionCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=16000)
    channel: str = Field("dashboard", pattern="^(dashboard|cli|webhook)$")


@router.get("/projects/{project_id}/missions")
async def list_missions(project_id: int, limit: int = Query(50, ge=1, le=200)):
    with session_scope() as s:
        if not s.get(Project, project_id):
            raise ProxyError(404, "Project not found.", code="not_found")
        missions = list(
            s.scalars(
                select(Mission)
                .where(Mission.project_id == project_id)
                .order_by(Mission.created_at.desc())
                .limit(limit)
            )
        )
        m_ids = [m.id for m in missions]
        tasks_by_m: dict[str, list[MissionTask]] = {mid: [] for mid in m_ids}
        if m_ids:
            for t in s.scalars(select(MissionTask).where(MissionTask.mission_id.in_(m_ids)).order_by(MissionTask.order_index, MissionTask.id)):
                tasks_by_m.setdefault(t.mission_id, []).append(t)
        return [serialize_mission(m, tasks=tasks_by_m.get(m.id, [])) for m in missions]


@router.post("/projects/{project_id}/missions")
async def create_mission(project_id: int, body: MissionCreate, request: Request):
    return await request.app.state.captain.start_mission(project_id, body.goal, channel=body.channel)


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str):
    with session_scope() as s:
        m = s.get(Mission, mission_id)
        if not m:
            raise ProxyError(404, "Mission not found.", code="not_found")
        tasks = list(s.scalars(select(MissionTask).where(MissionTask.mission_id == mission_id).order_by(MissionTask.order_index, MissionTask.id)))
        messages = list(s.scalars(select(MissionMessage).where(MissionMessage.mission_id == mission_id).order_by(MissionMessage.id)))
        return serialize_mission(m, tasks=tasks, messages=messages)


@router.post("/missions/{mission_id}/approve")
async def approve_mission(mission_id: str, request: Request):
    return await request.app.state.captain.approve_and_run(mission_id)


@router.post("/missions/{mission_id}/cancel")
async def cancel_mission(mission_id: str, request: Request):
    return await request.app.state.captain.cancel_mission(mission_id)


class RetryFailedBody(BaseModel):
    instruction: str = ""


@router.post("/missions/{mission_id}/retry-failed")
async def retry_failed_mission_tasks(mission_id: str, body: RetryFailedBody, request: Request):
    return await request.app.state.captain.retry_failed_tasks(mission_id, extra_instruction=body.instruction)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=16000)
    task_id: int | None = None
    channel: str = Field("dashboard", pattern="^(dashboard|cli|webhook)$")


@router.post("/missions/{mission_id}/messages")
async def post_message(mission_id: str, body: MessageCreate, request: Request):
    return await request.app.state.captain.post_user_message(
        mission_id, body.content, task_id=body.task_id, channel=body.channel
    )


class TaskPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, min_length=1)
    provider_name: str | None = None
    model: str | None = None


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, body: TaskPatch, request: Request):
    data = body.model_dump(exclude_unset=True)
    with session_scope() as s:
        t = s.get(MissionTask, task_id)
        if not t:
            raise ProxyError(404, "Task not found.", code="not_found")
        if t.status not in ("pending", "failed", "needs_input"):
            raise ProxyError(409, f"Task cannot be edited while in status {t.status!r}.", code="invalid_state")
        if "provider_name" in data and data["provider_name"]:
            p = s.scalar(select(Provider).where(Provider.name == data["provider_name"]))
            if not p or not p.enabled:
                raise ProxyError(400, f"Provider {data['provider_name']!r} is not enabled.", code="invalid_provider")
            t.provider_name = p.name
            if "model" not in data:
                t.model = p.default_model
        if "model" in data and data["model"] is not None:
            t.model = data["model"].strip()
        if "title" in data and data["title"]:
            t.title = data["title"].strip()
        if "description" in data and data["description"]:
            t.description = data["description"].strip()
        s.flush()
        out = serialize_task(t)
        mission_id = t.mission_id
    request.app.state.captain_bus.publish(mission_id, "task.updated", out)
    return out


class TaskRetryBody(BaseModel):
    instruction: str = ""


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: int, body: TaskRetryBody, request: Request):
    return await request.app.state.captain.retry_task(task_id, extra_instruction=body.instruction)


@router.get("/tasks/{task_id}/diff")
async def task_diff(task_id: int):
    with session_scope() as s:
        t = s.get(MissionTask, task_id)
        if not t:
            raise ProxyError(404, "Task not found.", code="not_found")
        m = s.get(Mission, t.mission_id)
        p = s.get(Project, m.project_id) if m else None
        wt_path = t.worktree_path
        base_branch = p.base_branch if p else "HEAD"
        branch_name = t.branch_name
    resolved_wt = Path(wt_path).expanduser().resolve() if wt_path else None
    if not resolved_wt or not resolved_wt.exists():
        return {"task_id": task_id, "branch_name": branch_name, "diff_stat": "", "diff": "", "exists": False}
    stat, diff = await get_worktree_diff(resolved_wt, base_branch)
    return {"task_id": task_id, "branch_name": branch_name, "diff_stat": stat, "diff": diff, "exists": True}


class TaskCleanupBody(BaseModel):
    delete_branch: bool = False


@router.post("/tasks/{task_id}/cleanup")
async def cleanup_task_worktree(task_id: int, body: TaskCleanupBody):
    with session_scope() as s:
        t = s.get(MissionTask, task_id)
        if not t:
            raise ProxyError(404, "Task not found.", code="not_found")
        if t.status == "running":
            raise ProxyError(409, "Cannot clean up worktree while task is running.", code="invalid_state")
        m = s.get(Mission, t.mission_id)
        p = s.get(Project, m.project_id) if m else None
        repo_path = Path(p.repo_path) if p else None
        wt_path = Path(t.worktree_path) if t.worktree_path else None
        branch_name = t.branch_name
        t.worktree_path = ""
    if repo_path and wt_path:
        await remove_worktree(repo_path, wt_path, branch_name=branch_name, delete_branch=body.delete_branch)
    return {"cleaned": task_id}


# ---------- Real-time SSE Streams ----------------------------------------------------------------

async def _sse_generator(request: Request, mission_id: str | None) -> AsyncIterator[str]:
    bus = request.app.state.captain_bus
    if bus.is_closed:
        return
    yield f"event: ready\ndata: {json.dumps({'mission_id': mission_id})}\n\n"
    async with bus.subscribe(mission_id) as q:
        try:
            while not bus.is_closed:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15.0)
                    if item is None:
                        break
                    yield f"event: {item['event']}\ndata: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            return


@router.get("/missions/{mission_id}/stream")
async def stream_mission(mission_id: str, request: Request):
    with session_scope() as s:
        if not s.get(Mission, mission_id):
            raise ProxyError(404, "Mission not found.", code="not_found")
    return StreamingResponse(
        _sse_generator(request, mission_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/captain/events")
async def stream_captain_events(request: Request):
    return StreamingResponse(
        _sse_generator(request, None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
