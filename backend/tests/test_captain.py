"""End-to-end and unit tests for AgentBridge Captain (Projects, Worktrees, Orchestrator, Channels)."""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app.captain.bus import MissionEventBus, NotificationEvent
from app.captain.channels import ChannelDispatcher, format_webhook_payload
from app.captain.orchestrator import _parse_plan
from app.captain.worktree import create_worktree, get_worktree_diff, remove_worktree, validate_git_repo


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# Demo Repo\n", encoding="utf-8")
    (path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)
    return path


def test_parse_plan_extracts_fenced_json_and_validates_providers():
    raw = """Here is the plan:
```json
{
  "title": "Add dark mode",
  "summary": "Split UI and tests across two agents",
  "tasks": [
    {"title": "Implement CSS", "description": "Add dark theme tokens", "provider": "claude", "model": "sonnet", "rationale": "UI"},
    {"title": "Add tests", "description": "Write vitest specs", "provider": "unknown_cli", "rationale": "Testing"}
  ]
}
```"""
    title, summary, tasks = _parse_plan(raw, "fallback goal", "claude", {"claude": "sonnet", "codex": "default"})
    assert title == "Add dark mode"
    assert "Split UI" in summary
    assert len(tasks) == 2
    assert tasks[0]["provider_name"] == "claude"
    # Unknown provider falls back cleanly to fallback_provider
    assert tasks[1]["provider_name"] == "claude"


def test_format_webhook_payload_variants():
    notif = NotificationEvent(
        id=1,
        kind="completed",
        project_id=1,
        project_name="Demo",
        mission_id="m123",
        task_id=None,
        title="Mission completed",
        body="All tasks done.",
        created_at="2026-11-26T00:00:00+00:00",
    )
    discord_body, _ = format_webhook_payload("https://discord.com/api/webhooks/1/abc", notif)
    assert isinstance(discord_body, dict) and "**[Demo] Mission completed**" in discord_body["content"]

    slack_body, _ = format_webhook_payload("https://hooks.slack.com/services/T0/B0/X", notif)
    assert isinstance(slack_body, dict) and "*[Demo] Mission completed*" in slack_body["text"]

    ntfy_body, ntfy_headers = format_webhook_payload("https://ntfy.sh/my-topic", notif)
    assert ntfy_body == "All tasks done."
    assert ntfy_headers["Title"] == "[Demo] Mission completed"

    generic_body, _ = format_webhook_payload("https://example.com/hook", notif)
    assert isinstance(generic_body, dict) and generic_body["event"] == "completed" and generic_body["mission_id"] == "m123"


def test_webhook_delivery_with_mock_transport():
    received: list[tuple[str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        received.append((str(request.url), request.content))
        return httpx.Response(200, json={"ok": True})

    async def run():
        bus = MissionEventBus()
        dispatcher = ChannelDispatcher(bus, transport=httpx.MockTransport(handler))
        notif = NotificationEvent(
            id=1,
            kind="completed",
            project_id=7,
            project_name="TestProj",
            mission_id="abc",
            task_id=None,
            title="Done",
            body="Finished.",
            created_at="2026-11-26T00:00:00+00:00",
        )
        code = await dispatcher.deliver_webhook("https://example.com/webhook", notif)
        assert code == 200
        assert len(received) == 1
        payload = json.loads(received[0][1])
        assert payload["project"] == "TestProj"
        assert payload["event"] == "completed"

    asyncio.run(run())


def test_git_worktree_lifecycle(tmp_path: Path):
    repo = _init_git_repo(tmp_path / "repo")
    wt = tmp_path / "wt-1"

    async def run():
        info = await validate_git_repo(repo)
        assert info["base_branch"] == "main"
        await create_worktree(repo, "main", wt, "captain/m1/task-1")
        assert (wt / "app.py").exists()
        (wt / "new_file.txt").write_text("hello worktree\n", encoding="utf-8")
        stat, diff = await get_worktree_diff(wt, "main")
        assert "new_file.txt" in stat
        assert "+hello worktree" in diff
        await remove_worktree(repo, wt, branch_name="captain/m1/task-1", delete_branch=True)
        assert not wt.exists()

    asyncio.run(run())


def test_git_worktree_resolves_relative_paths_and_recovers_stale_branch(tmp_path: Path, monkeypatch):
    repo = _init_git_repo(tmp_path / "target-repo")
    server_cwd = tmp_path / "server-cwd"
    server_cwd.mkdir()
    monkeypatch.chdir(server_cwd)

    async def run():
        # Passing a relative worktree path must resolve against server_cwd, NOT inside target-repo.
        rel_wt = Path("data/worktrees/demo/m1/task-1")
        created = await create_worktree(repo, "main", rel_wt, "captain/m1/task-rel")
        assert created.is_absolute()
        assert created == (server_cwd / rel_wt).resolve()
        assert created.is_dir()
        assert not (repo / rel_wt).exists()

        # Re-creating the same branch at a new path should cleanly detach/remove the stale worktree.
        new_wt = server_cwd / "data/worktrees/demo/m1/task-1-moved"
        moved = await create_worktree(repo, "main", new_wt, "captain/m1/task-rel")
        assert moved.is_dir()
        assert not created.exists()

        await remove_worktree(repo, moved, branch_name="captain/m1/task-rel", delete_branch=True)

    asyncio.run(run())


def _wait_for_mission_status(live, mission_id: str, targets: set[str], timeout_s: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = live.admin("GET", f"/missions/{mission_id}")
        if last["status"] in targets:
            return last
        time.sleep(0.15)
    raise AssertionError(f"Mission {mission_id} stayed in {last['status'] if last else None}, expected one of {targets}")


def test_captain_project_and_mission_lifecycle(live, tmp_path: Path):
    repo = _init_git_repo(tmp_path / "captain-demo")
    # Ensure at least two fake CLI providers are enabled
    live.admin("PUT", "/providers/claude", json={"enabled": True, "binary_path": live.wrappers["claude"], "api_key_enc": ""})
    live.admin("PUT", "/providers/claude/secret", json={"api_key": "fake-key"})
    live.admin("PUT", "/providers/codex", json={"enabled": True, "binary_path": live.wrappers["codex"]})
    live.admin("PUT", "/providers/codex/secret", json={"api_key": "fake-key"})

    # Reject non-git folder
    bad_dir = tmp_path / "not-a-repo"
    bad_dir.mkdir()
    r = httpx.post(
        live.base + "/admin/projects",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"name": "Bad", "repo_path": str(bad_dir)},
    )
    assert r.status_code == 400

    # Create git project
    proj = live.admin(
        "POST",
        "/projects",
        json={
            "name": "Captain Demo",
            "repo_path": str(repo),
            "captain_provider": "claude",
            "approval_mode": "manual",
            "agent_roles": {"claude": "backend", "codex": "tests"},
        },
    )
    assert proj["slug"] == "captain-demo"
    assert proj["base_branch"] == "main"

    # Start mission -> plans via fake CLI -> pauses in awaiting_approval
    mission = live.admin("POST", f"/projects/{proj['id']}/missions", json={"goal": "Add a greeting helper and test it", "channel": "dashboard"})
    planned = _wait_for_mission_status(live, mission["id"], {"awaiting_approval", "failed"})
    assert planned["status"] == "awaiting_approval"
    assert len(planned["tasks"]) >= 1

    # Reassign first task to codex before approving
    first_task = planned["tasks"][0]
    edited = live.admin("PATCH", f"/tasks/{first_task['id']}", json={"provider_name": "codex"})
    assert edited["provider_name"] == "codex"

    # Approve and wait for completion
    live.admin("POST", f"/missions/{mission['id']}/approve", json={})
    done = _wait_for_mission_status(live, mission["id"], {"completed", "failed"})
    assert done["status"] == "completed"
    assert done["final_summary"]
    assert any(m["kind"] == "order" for m in done["messages"])
    assert any(m["kind"] == "plan" for m in done["messages"])

    # Diff & cleanup endpoints work on completed task
    diff = live.admin("GET", f"/tasks/{first_task['id']}/diff")
    assert diff["exists"] is True
    assert diff["branch_name"].startswith(f"captain/{mission['id']}/task-")

    # Status bar exposes captain summary + notifications
    sb = live.admin("GET", "/status-bar")
    assert "captain" in sb
    assert len(sb["captain"]["notifications"]) >= 1

    cleaned = live.admin("POST", f"/tasks/{first_task['id']}/cleanup", json={"delete_branch": False})
    assert cleaned["cleaned"] == first_task["id"]

    # Delete project cleanly
    deleted = live.admin("DELETE", f"/projects/{proj['id']}?cleanup_worktrees=true")
    assert deleted["deleted"] == proj["id"]
