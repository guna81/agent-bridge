"""Captain Orchestrator: plans, delegates, monitors, and synthesizes multi-CLI missions."""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from ..adapters.base import Done, Error, NormalizedRequest, TextDelta, Usage
from ..config import get_settings
from ..db import session_scope
from ..errors import ProxyError
from ..logging_setup import log
from ..models import Mission, MissionMessage, MissionTask, Project, Provider, iso_utc, utcnow
from ..service import ServiceState, run_chat
from .bus import MissionEventBus
from .channels import ChannelDispatcher
from .worktree import GitError, collect_repo_context, create_worktree, get_worktree_diff

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def serialize_task(t: MissionTask) -> dict:
    return {
        "id": t.id,
        "mission_id": t.mission_id,
        "order_index": t.order_index,
        "title": t.title,
        "description": t.description,
        "provider_name": t.provider_name,
        "model": t.model,
        "rationale": t.rationale,
        "status": t.status,
        "worktree_path": t.worktree_path,
        "branch_name": t.branch_name,
        "diff_stat": t.diff_stat,
        "output_text": t.output_text,
        "error": t.error,
        "cost_usd": t.cost_usd,
        "duration_ms": t.duration_ms,
        "created_at": iso_utc(t.created_at),
        "started_at": iso_utc(t.started_at),
        "completed_at": iso_utc(t.completed_at),
    }


def serialize_message(m: MissionMessage) -> dict:
    return {
        "id": m.id,
        "mission_id": m.mission_id,
        "task_id": m.task_id,
        "sender_type": m.sender_type,
        "sender_name": m.sender_name,
        "channel": m.channel,
        "kind": m.kind,
        "content": m.content,
        "meta": m.meta or {},
        "created_at": iso_utc(m.created_at),
    }


def serialize_mission(m: Mission, tasks: list[MissionTask] | None = None, messages: list[MissionMessage] | None = None) -> dict:
    out = {
        "id": m.id,
        "project_id": m.project_id,
        "title": m.title,
        "goal": m.goal,
        "status": m.status,
        "captain_provider": m.captain_provider,
        "captain_model": m.captain_model,
        "plan_summary": m.plan_summary,
        "final_summary": m.final_summary,
        "error": m.error,
        "created_at": iso_utc(m.created_at),
        "updated_at": iso_utc(m.updated_at),
        "completed_at": iso_utc(m.completed_at),
    }
    if tasks is not None:
        out["tasks"] = [serialize_task(t) for t in tasks]
    if messages is not None:
        out["messages"] = [serialize_message(msg) for msg in messages]
    return out


def _extract_json_object(raw: str) -> dict | None:
    text = raw.strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def _parse_plan(raw: str, goal: str, fallback_provider: str, provider_models: dict[str, str]) -> tuple[str, str, list[dict]]:
    obj = _extract_json_object(raw)
    if not obj or not isinstance(obj.get("tasks"), list) or not obj["tasks"]:
        # Graceful fallback: treat the goal as a single task assigned to the fallback provider.
        return (
            goal[:80].strip() or "Mission",
            raw.strip()[:500] or "Single-task execution plan.",
            [{
                "title": goal[:100].strip() or "Execute user order",
                "description": goal,
                "provider_name": fallback_provider,
                "model": provider_models.get(fallback_provider, ""),
                "rationale": "Default assignment.",
            }],
        )
    title = str(obj.get("title") or goal[:80]).strip()[:200]
    summary = str(obj.get("summary") or "").strip()
    tasks: list[dict] = []
    for idx, item in enumerate(obj["tasks"][:8]):
        if not isinstance(item, dict):
            continue
        pname = str(item.get("provider") or item.get("provider_name") or fallback_provider).strip()
        if pname not in provider_models:
            pname = fallback_provider
        model = str(item.get("model") or provider_models.get(pname, "")).strip()
        tasks.append({
            "title": str(item.get("title") or f"Task {idx + 1}").strip()[:200],
            "description": str(item.get("description") or goal).strip(),
            "provider_name": pname,
            "model": model,
            "rationale": str(item.get("rationale") or "").strip(),
        })
    if not tasks:
        tasks.append({
            "title": goal[:100].strip() or "Execute user order",
            "description": goal,
            "provider_name": fallback_provider,
            "model": provider_models.get(fallback_provider, ""),
            "rationale": "Default assignment.",
        })
    return title, summary, tasks


def _quota_lines() -> dict[str, str]:
    try:
        from ..rate_limits_reader import get_all_cli_rate_limits

        limits = get_all_cli_rate_limits() or {}
    except Exception:
        return {}
    mapping = {"claude": "claude", "codex": "codex", "agy": "antigravity"}
    out: dict[str, str] = {}
    for kind, key in mapping.items():
        data = limits.get(key)
        if not isinstance(data, dict):
            continue
        parts = []
        for win_key, label in (("five_hour", "5h"), ("weekly", "weekly")):
            win = data.get(win_key)
            if isinstance(win, dict) and win.get("left_percent") is not None:
                parts.append(f"{label}: {int(round(win['left_percent']))}% left")
        if parts:
            out[kind] = ", ".join(parts)
    return out


class CaptainOrchestrator:
    """Manages project-scoped Captain planning, parallel worker execution, and channels."""

    def __init__(self, service: ServiceState, bus: MissionEventBus, channels: ChannelDispatcher):
        self.service = service
        self.bus = bus
        self.channels = channels
        self._active: dict[str, set[asyncio.Task]] = {}

    def _track(self, mission_id: str, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._active.setdefault(mission_id, set()).add(task)

        def _done(t: asyncio.Task) -> None:
            s = self._active.get(mission_id)
            if s:
                s.discard(t)
                if not s:
                    self._active.pop(mission_id, None)

        task.add_done_callback(_done)
        return task

    def _add_message(
        self,
        mission_id: str,
        *,
        sender_type: str,
        sender_name: str,
        kind: str,
        content: str,
        channel: str = "system",
        task_id: int | None = None,
        meta: dict | None = None,
    ) -> dict:
        with session_scope() as s:
            msg = MissionMessage(
                mission_id=mission_id,
                task_id=task_id,
                sender_type=sender_type,
                sender_name=sender_name,
                channel=channel,
                kind=kind,
                content=content,
                meta=meta or {},
            )
            s.add(msg)
            s.flush()
            out = serialize_message(msg)
        self.bus.publish(mission_id, "message.created", out)
        return out

    def _publish_mission(self, mission_id: str) -> None:
        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m:
                return
            tasks = list(s.scalars(select(MissionTask).where(MissionTask.mission_id == mission_id).order_by(MissionTask.order_index, MissionTask.id)))
            out = serialize_mission(m, tasks=tasks)
        self.bus.publish(mission_id, "mission.updated", out)

    def _eligible_providers(self, s, project: Project) -> list[Provider]:
        providers = list(s.scalars(select(Provider).where(Provider.enabled.is_(True)).order_by(Provider.id)))
        allowed = set(project.allowed_providers or [])
        if allowed:
            filtered = [p for p in providers if p.name in allowed]
            if filtered:
                return filtered
        return providers

    async def start_mission(self, project_id: int, goal: str, channel: str = "dashboard") -> dict:
        goal = goal.strip()
        if not goal:
            raise ProxyError(400, "Mission goal cannot be empty.", code="invalid_request")

        with session_scope() as s:
            project = s.get(Project, project_id)
            if not project:
                raise ProxyError(404, "Project not found.", code="not_found")
            eligible = self._eligible_providers(s, project)
            if not eligible:
                raise ProxyError(400, "No enabled providers available for this project. Enable a provider first.", code="no_providers")

            captain_provider = next((p for p in eligible if p.name == project.captain_provider), None) or eligible[0]
            captain_model = project.captain_model or captain_provider.default_model
            mission_id = uuid.uuid4().hex[:12]
            m = Mission(
                id=mission_id,
                project_id=project.id,
                title=goal[:80],
                goal=goal,
                status="planning",
                captain_provider=captain_provider.name,
                captain_model=captain_model,
            )
            s.add(m)
            s.flush()
            out = serialize_mission(m, tasks=[], messages=[])

        self._add_message(
            mission_id,
            sender_type="user",
            sender_name="You",
            channel=channel,
            kind="order",
            content=goal,
        )
        self._publish_mission(mission_id)
        self._track(mission_id, self._plan_mission(mission_id))
        return out

    async def _run_provider_once(
        self,
        provider: Provider,
        model: str,
        system: str,
        prompt: str,
        *,
        mode_override: str,
        workdir_override: Path | None = None,
        project_id: int | None = None,
        budget_cap: float | None = None,
        on_delta=None,
    ) -> tuple[str, float, int, str | None]:
        req = NormalizedRequest(model=model or provider.default_model, system=system, turns=[("user", prompt)], stream=True)
        req_id = "cap-" + uuid.uuid4().hex[:12]
        t0 = time.monotonic()
        parts: list[str] = []
        cost_usd = 0.0
        error_msg: str | None = None
        gen = run_chat(
            self.service,
            provider,
            None,
            req,
            req_id,
            budget_cap=budget_cap,
            workdir_override=workdir_override,
            mode_override=mode_override,  # type: ignore[arg-type]
            project_id=project_id,
        )
        try:
            async for ev in gen:
                if isinstance(ev, TextDelta):
                    parts.append(ev.text)
                    if on_delta:
                        on_delta(ev.text)
                elif isinstance(ev, Usage) and ev.cost_usd is not None:
                    cost_usd = ev.cost_usd
                elif isinstance(ev, Error):
                    error_msg = f"{ev.code}: {ev.message}"
                elif isinstance(ev, Done):
                    pass
        except ProxyError as exc:
            error_msg = exc.message
        finally:
            await gen.aclose()
        return "".join(parts), cost_usd, int((time.monotonic() - t0) * 1000), error_msg

    async def _plan_mission(self, mission_id: str, *, feedback: str = "") -> None:
        try:
            with session_scope() as s:
                m = s.get(Mission, mission_id)
                if not m:
                    return
                project = s.get(Project, m.project_id)
                if not project:
                    return
                eligible = self._eligible_providers(s, project)
                captain_p = next((p for p in eligible if p.name == m.captain_provider), eligible[0])
                for p in eligible:
                    s.expunge(p)
                s.expunge(project)
                goal = m.goal
                captain_model = m.captain_model or captain_p.default_model

            quotas = await asyncio.to_thread(_quota_lines)
            repo_ctx = await collect_repo_context(Path(project.repo_path))

            agent_lines = []
            provider_models: dict[str, str] = {}
            for p in eligible:
                provider_models[p.name] = p.default_model
                role = (project.agent_roles or {}).get(p.name, "general coding agent")
                q = quotas.get(p.kind, "quota unknown")
                agent_lines.append(f"- {p.name} (kind={p.kind}, default_model={p.default_model}, role={role}, {q})")

            system = (
                "You are AgentBridge Captain, an engineering manager coordinating coding CLI agents in a local git repository. "
                "Break the user's order into 1 to 4 independent, parallelizable coding tasks that can run in isolated git worktrees. "
                "Assign each task to the best available agent based on its role and remaining subscription quota. "
                "Respond ONLY with valid JSON matching this schema:\n"
                '{"title": "short mission title", "summary": "brief plan overview", '
                '"tasks": [{"title": "...", "description": "clear actionable prompt for the coding agent", '
                '"provider": "<provider_name>", "model": "<model_slug>", "rationale": "why this agent"}]}'
            )
            prompt_parts = [
                f"Project: {project.name} ({project.repo_path})",
                f"User order:\n{goal}",
                "Available coding agents:\n" + "\n".join(agent_lines),
            ]
            if feedback:
                prompt_parts.append(f"User feedback on the previous plan (revise the plan accordingly):\n{feedback}")
            if project.instructions:
                prompt_parts.append(f"Project Captain instructions:\n{project.instructions}")
            if repo_ctx:
                prompt_parts.append(f"Repository context:\n{repo_ctx}")

            text, _, _, err = await self._run_provider_once(
                captain_p,
                captain_model,
                system,
                "\n\n".join(prompt_parts),
                mode_override="raw",
                project_id=project.id,
                budget_cap=project.max_budget_usd,
            )
            if err:
                with session_scope() as s:
                    m = s.get(Mission, mission_id)
                    if m:
                        m.status = "failed"
                        m.error = err
                        m.updated_at = utcnow()
                self._add_message(mission_id, sender_type="captain", sender_name=captain_p.name, kind="error", content=f"Planning failed: {err}")
                self._publish_mission(mission_id)
                self.channels.notify(
                    kind="failed",
                    project_id=project.id,
                    project_name=project.name,
                    mission_id=mission_id,
                    title="Mission planning failed",
                    body=err,
                    webhook_url=project.webhook_url,
                    webhook_events=project.webhook_events,
                )
                return

            title, summary, planned_tasks = _parse_plan(text, goal, captain_p.name, provider_models)
            with session_scope() as s:
                m = s.get(Mission, mission_id)
                if not m or m.status == "cancelled":
                    return
                m.title = title
                m.plan_summary = summary
                m.status = "running" if project.approval_mode == "auto" else "awaiting_approval"
                m.updated_at = utcnow()
                for idx, item in enumerate(planned_tasks):
                    s.add(MissionTask(
                        mission_id=mission_id,
                        order_index=idx,
                        title=item["title"],
                        description=item["description"],
                        provider_name=item["provider_name"],
                        model=item["model"],
                        rationale=item["rationale"],
                        status="pending",
                    ))

            plan_md = (summary + "\n\n" if summary else "") + "\n".join(
                f"{i + 1}. **{t['title']}** → `{t['provider_name']}/{t['model']}`" + (f" — {t['rationale']}" if t["rationale"] else "")
                for i, t in enumerate(planned_tasks)
            )
            self._add_message(
                mission_id,
                sender_type="captain",
                sender_name=captain_p.name,
                kind="plan",
                content=plan_md,
            )
            self._publish_mission(mission_id)

            if project.approval_mode == "auto":
                await self._execute_pending_tasks(mission_id)
            else:
                self.channels.notify(
                    kind="awaiting_approval",
                    project_id=project.id,
                    project_name=project.name,
                    mission_id=mission_id,
                    title=f"Plan ready: {title}",
                    body=f"{len(planned_tasks)} task(s) ready for approval.",
                    webhook_url=project.webhook_url,
                    webhook_events=project.webhook_events,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("captain.plan_exception", mission_id=mission_id, error=str(exc))
            with session_scope() as s:
                m = s.get(Mission, mission_id)
                if m and m.status != "cancelled":
                    m.status = "failed"
                    m.error = str(exc)
            self._publish_mission(mission_id)

    async def approve_and_run(self, mission_id: str) -> dict:
        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m:
                raise ProxyError(404, "Mission not found.", code="not_found")
            if m.status not in ("awaiting_approval", "needs_input"):
                raise ProxyError(409, f"Mission is in status {m.status!r} and cannot be approved.", code="invalid_state")
            m.status = "running"
            m.updated_at = utcnow()
            tasks = list(s.scalars(select(MissionTask).where(MissionTask.mission_id == mission_id).order_by(MissionTask.order_index, MissionTask.id)))
            out = serialize_mission(m, tasks=tasks)

        self._add_message(mission_id, sender_type="system", sender_name="Captain", kind="status", content="Plan approved. Dispatching tasks to agents…")
        self._publish_mission(mission_id)
        self._track(mission_id, self._execute_pending_tasks(mission_id))
        return out

    async def _execute_pending_tasks(self, mission_id: str, *, extra_instruction: str = "") -> None:
        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m:
                return
            project = s.get(Project, m.project_id)
            if not project:
                return
            task_ids = [
                t.id
                for t in s.scalars(
                    select(MissionTask)
                    .where(MissionTask.mission_id == mission_id, MissionTask.status.in_(("pending", "queued")))
                    .order_by(MissionTask.order_index, MissionTask.id)
                )
            ]
            s.expunge(project)

        if not task_ids:
            return

        worker_coros = [self._run_single_task(mission_id, tid, project, extra_instruction=extra_instruction) for tid in task_ids]
        await asyncio.gather(*worker_coros, return_exceptions=True)
        await self._finalize_mission(mission_id)

    async def _run_single_task(self, mission_id: str, task_id: int, project: Project, extra_instruction: str = "") -> None:
        with session_scope() as s:
            t = s.get(MissionTask, task_id)
            if not t or t.status == "cancelled":
                return
            p = s.scalar(select(Provider).where(Provider.name == t.provider_name))
            if not p or not p.enabled:
                t.status = "failed"
                t.error = f"Provider {t.provider_name!r} is missing or disabled."
                t.completed_at = utcnow()
                self.bus.publish(mission_id, "task.updated", serialize_task(t))
                return
            s.expunge(p)
            branch_name = t.branch_name or f"captain/{mission_id}/task-{t.id}"
            wt_root = get_settings().data_dir.expanduser().resolve() / "worktrees" / project.slug / mission_id
            stored_wt = Path(t.worktree_path) if t.worktree_path else None
            wt_path = stored_wt.resolve() if (stored_wt and stored_wt.is_absolute()) else (wt_root / f"task-{t.id}")
            t.branch_name = branch_name
            t.worktree_path = str(wt_path)
            t.status = "running"
            t.error = ""
            t.started_at = utcnow()
            task_title = t.title
            task_desc = t.description
            task_model = t.model or p.default_model
            self.bus.publish(mission_id, "task.updated", serialize_task(t))

        self._add_message(
            mission_id,
            sender_type="system",
            sender_name=p.name,
            kind="status",
            task_id=task_id,
            content=f"Starting **{task_title}** on `{p.name}/{task_model}` in branch `{branch_name}`.",
        )

        try:
            if not wt_path.exists():
                await create_worktree(Path(project.repo_path), project.base_branch, wt_path, branch_name)
        except GitError as exc:
            with session_scope() as s:
                t = s.get(MissionTask, task_id)
                if t:
                    t.status = "failed"
                    t.error = str(exc)
                    t.completed_at = utcnow()
                    self.bus.publish(mission_id, "task.updated", serialize_task(t))
            self._add_message(mission_id, sender_type="agent", sender_name=p.name, kind="error", task_id=task_id, content=str(exc))
            return

        system = (
            f"You are working on project '{project.name}' inside an isolated git worktree on branch '{branch_name}'. "
            "Complete the assigned task directly in this repository. Do not push or switch branches. "
            "If you are blocked and need user clarification, start your final reply with 'NEEDS_INPUT:'."
        )
        if project.instructions:
            system += f"\n\nProject instructions:\n{project.instructions}"
        prompt = f"Task: {task_title}\n\n{task_desc}"
        if extra_instruction:
            prompt += f"\n\nAdditional user guidance:\n{extra_instruction}"

        def _on_delta(chunk: str) -> None:
            self.bus.publish(mission_id, "task.delta", {"task_id": task_id, "provider_name": p.name, "delta": chunk})

        text, cost, duration_ms, err = await self._run_provider_once(
            p,
            task_model,
            system,
            prompt,
            mode_override="agent",
            workdir_override=wt_path,
            project_id=project.id,
            budget_cap=project.max_budget_usd,
            on_delta=_on_delta,
        )

        diff_stat, _ = await get_worktree_diff(wt_path, project.base_branch)
        needs_input = (err is None) and text.lstrip().startswith("NEEDS_INPUT:")

        with session_scope() as s:
            t = s.get(MissionTask, task_id)
            if not t or t.status == "cancelled":
                return
            t.output_text = text
            t.diff_stat = diff_stat
            t.cost_usd = cost
            t.duration_ms = duration_ms
            t.completed_at = utcnow()
            if err:
                t.status = "failed"
                t.error = err
            elif needs_input:
                t.status = "needs_input"
            else:
                t.status = "completed"
            task_out = serialize_task(t)

        self.bus.publish(mission_id, "task.updated", task_out)
        if err:
            self._add_message(mission_id, sender_type="agent", sender_name=p.name, kind="error", task_id=task_id, content=f"**{task_title}** failed: {err}")
        elif needs_input:
            self._add_message(mission_id, sender_type="agent", sender_name=p.name, kind="question", task_id=task_id, content=text)
            self.channels.notify(
                kind="needs_input",
                project_id=project.id,
                project_name=project.name,
                mission_id=mission_id,
                task_id=task_id,
                title=f"Agent needs input: {task_title}",
                body=text[:300],
                webhook_url=project.webhook_url,
                webhook_events=project.webhook_events,
            )
        else:
            snippet = text.strip()[:1200] or "(no text output)"
            self._add_message(
                mission_id,
                sender_type="agent",
                sender_name=p.name,
                kind="result",
                task_id=task_id,
                content=snippet + (f"\n\n```\n{diff_stat}\n```" if diff_stat else ""),
            )

    async def _finalize_mission(self, mission_id: str) -> None:
        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m or m.status == "cancelled":
                return
            project = s.get(Project, m.project_id)
            if not project:
                return
            tasks = list(s.scalars(select(MissionTask).where(MissionTask.mission_id == mission_id).order_by(MissionTask.order_index, MissionTask.id)))
            captain_p = s.scalar(select(Provider).where(Provider.name == m.captain_provider))
            if captain_p:
                s.expunge(captain_p)
            s.expunge(project)
            mission_title = m.title
            mission_goal = m.goal
            captain_model = m.captain_model
            task_summaries = [
                f"- [{t.status}] {t.title} ({t.provider_name}, branch={t.branch_name}): {(t.error or t.output_text or '')[:400]}\n  Diff: {t.diff_stat or 'no file changes'}"
                for t in tasks
            ]
            statuses = {t.status for t in tasks}

        if "needs_input" in statuses:
            final_status = "needs_input"
            summary = "One or more tasks need your input before the mission can finish."
        elif statuses and statuses == {"failed"}:
            final_status = "failed"
            summary = "All tasks failed. Review the task errors and retry."
        else:
            final_status = "completed"
            summary = ""
            if captain_p and captain_p.enabled:
                synth_text, _, _, err = await self._run_provider_once(
                    captain_p,
                    captain_model or captain_p.default_model,
                    "You are AgentBridge Captain. Summarize the completed multi-agent mission concisely in markdown, noting which branches have changes ready to review.",
                    f"Mission goal: {mission_goal}\n\nTask results:\n" + "\n".join(task_summaries),
                    mode_override="raw",
                    project_id=project.id,
                    budget_cap=project.max_budget_usd,
                )
                if not err and synth_text.strip():
                    summary = synth_text.strip()
            if not summary:
                summary = "Mission finished:\n" + "\n".join(task_summaries)

        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m or m.status == "cancelled":
                return
            m.status = final_status
            m.final_summary = summary
            m.updated_at = utcnow()
            if final_status in ("completed", "failed"):
                m.completed_at = utcnow()

        self._add_message(
            mission_id,
            sender_type="captain",
            sender_name=captain_p.name if captain_p else "Captain",
            kind="result" if final_status == "completed" else "status",
            content=summary,
        )
        self._publish_mission(mission_id)
        self.channels.notify(
            kind=final_status,
            project_id=project.id,
            project_name=project.name,
            mission_id=mission_id,
            title=f"Mission {final_status}: {mission_title}",
            body=summary[:300],
            webhook_url=project.webhook_url,
            webhook_events=project.webhook_events,
        )

    async def retry_task(self, task_id: int, extra_instruction: str = "") -> dict:
        with session_scope() as s:
            t = s.get(MissionTask, task_id)
            if not t:
                raise ProxyError(404, "Task not found.", code="not_found")
            m = s.get(Mission, t.mission_id)
            if not m:
                raise ProxyError(404, "Mission not found.", code="not_found")
            project = s.get(Project, m.project_id)
            if not project:
                raise ProxyError(404, "Project not found.", code="not_found")
            t.status = "pending"
            t.error = ""
            m.status = "running"
            m.updated_at = utcnow()
            mission_id = m.id
            s.expunge(project)
            out = serialize_task(t)

        self._publish_mission(mission_id)

        async def _rerun() -> None:
            await self._run_single_task(mission_id, task_id, project, extra_instruction=extra_instruction)
            await self._finalize_mission(mission_id)

        self._track(mission_id, _rerun())
        return out

    async def retry_failed_tasks(self, mission_id: str, extra_instruction: str = "") -> dict:
        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m:
                raise ProxyError(404, "Mission not found.", code="not_found")
            failed = list(
                s.scalars(
                    select(MissionTask)
                    .where(MissionTask.mission_id == mission_id, MissionTask.status == "failed")
                    .order_by(MissionTask.order_index, MissionTask.id)
                )
            )
            if not failed:
                raise ProxyError(409, "No failed tasks to retry.", code="invalid_state")
            for t in failed:
                t.status = "pending"
                t.error = ""
            m.status = "running"
            m.error = ""
            m.updated_at = utcnow()
            all_tasks = list(
                s.scalars(
                    select(MissionTask)
                    .where(MissionTask.mission_id == mission_id)
                    .order_by(MissionTask.order_index, MissionTask.id)
                )
            )
            out = serialize_mission(m, tasks=all_tasks)

        self._add_message(
            mission_id,
            sender_type="system",
            sender_name="Captain",
            kind="status",
            content=f"Retrying {len(failed)} failed task(s)…",
        )
        self._publish_mission(mission_id)
        self._track(mission_id, self._execute_pending_tasks(mission_id, extra_instruction=extra_instruction))
        return out

    async def _answer_followup(self, mission_id: str, question: str) -> None:
        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m:
                return
            project = s.get(Project, m.project_id)
            if not project:
                return
            captain_p = s.scalar(select(Provider).where(Provider.name == m.captain_provider))
            if not captain_p or not captain_p.enabled:
                return
            tasks = list(
                s.scalars(
                    select(MissionTask)
                    .where(MissionTask.mission_id == mission_id)
                    .order_by(MissionTask.order_index, MissionTask.id)
                )
            )
            s.expunge(captain_p)
            s.expunge(project)
            captain_model = m.captain_model or captain_p.default_model
            goal = m.goal
            final_summary = m.final_summary
            task_lines = [
                f"- [{t.status}] {t.title} ({t.provider_name}, branch={t.branch_name}): {(t.output_text or t.error or '')[:500]}"
                for t in tasks
            ]

        prompt = (
            f"Mission goal: {goal}\n\n"
            f"Mission summary:\n{final_summary or '(none)'}\n\n"
            f"Tasks:\n" + "\n".join(task_lines) + "\n\n"
            f"User follow-up:\n{question}"
        )
        text, _, _, err = await self._run_provider_once(
            captain_p,
            captain_model,
            "You are AgentBridge Captain. Answer the user's follow-up question concisely based on the mission results.",
            prompt,
            mode_override="raw",
            project_id=project.id,
            budget_cap=project.max_budget_usd,
        )
        self._add_message(
            mission_id,
            sender_type="captain",
            sender_name=captain_p.name,
            kind="error" if err else "result",
            content=f"Could not reply: {err}" if err else (text.strip() or "(no response)"),
        )
        self._publish_mission(mission_id)

    async def post_user_message(self, mission_id: str, content: str, *, task_id: int | None = None, channel: str = "dashboard") -> dict:
        content = content.strip()
        if not content:
            raise ProxyError(400, "Message content cannot be empty.", code="invalid_request")
        mission_status = ""
        has_failed_tasks = False
        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m:
                raise ProxyError(404, "Mission not found.", code="not_found")
            mission_status = m.status
            if task_id is None:
                blocked = s.scalar(
                    select(MissionTask).where(MissionTask.mission_id == mission_id, MissionTask.status == "needs_input").limit(1)
                )
                if blocked:
                    task_id = blocked.id
                else:
                    has_failed_tasks = (
                        s.scalar(
                            select(MissionTask.id).where(MissionTask.mission_id == mission_id, MissionTask.status == "failed").limit(1)
                        )
                        is not None
                    )
            elif s.get(MissionTask, task_id) is None:
                raise ProxyError(404, "Task not found.", code="not_found")

        msg = self._add_message(
            mission_id,
            sender_type="user",
            sender_name="You",
            channel=channel,
            kind="reply",
            task_id=task_id,
            content=content,
        )
        if task_id is not None:
            await self.retry_task(task_id, extra_instruction=content)
        elif has_failed_tasks:
            await self.retry_failed_tasks(mission_id, extra_instruction=content)
        elif mission_status == "awaiting_approval":
            with session_scope() as s:
                m = s.get(Mission, mission_id)
                if m:
                    for old in list(s.scalars(select(MissionTask).where(MissionTask.mission_id == mission_id, MissionTask.status == "pending"))):
                        s.delete(old)
                    m.status = "planning"
                    m.updated_at = utcnow()
            self._add_message(mission_id, sender_type="system", sender_name="Captain", kind="status", content="Revising plan based on your feedback…")
            self._publish_mission(mission_id)
            self._track(mission_id, self._plan_mission(mission_id, feedback=content))
        elif mission_status == "completed":
            self._track(mission_id, self._answer_followup(mission_id, content))
        return msg

    async def cancel_mission(self, mission_id: str) -> dict:
        with session_scope() as s:
            m = s.get(Mission, mission_id)
            if not m:
                raise ProxyError(404, "Mission not found.", code="not_found")
            m.status = "cancelled"
            m.completed_at = utcnow()
            m.updated_at = utcnow()
            tasks = list(s.scalars(select(MissionTask).where(MissionTask.mission_id == mission_id)))
            for t in tasks:
                if t.status in ("pending", "queued", "running", "needs_input"):
                    t.status = "cancelled"
                    t.completed_at = utcnow()
            out = serialize_mission(m, tasks=tasks)

        for t in list(self._active.get(mission_id, ())):
            t.cancel()
        self._add_message(mission_id, sender_type="system", sender_name="Captain", kind="status", content="Mission cancelled by user.")
        self._publish_mission(mission_id)
        return out

    async def shutdown(self) -> None:
        all_tasks = [t for group in self._active.values() for t in group]
        for t in all_tasks:
            t.cancel()
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        await self.channels.shutdown()
