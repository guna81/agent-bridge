"""Git worktree lifecycle and repository context helpers for Captain tasks."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git repository or worktree operation fails."""


async def _run_git(cwd: Path, *args: str, timeout: float = 30.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from None
    return proc.returncode or 0, out_b.decode("utf-8", errors="replace"), err_b.decode("utf-8", errors="replace")


async def validate_git_repo(repo_path: Path) -> dict:
    """Verify repo_path is an existing git repository and detect its default branch."""
    resolved = repo_path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise GitError(f"Repository path does not exist or is not a directory: {resolved}")
    rc, top, err = await _run_git(resolved, "rev-parse", "--show-toplevel")
    if rc != 0:
        raise GitError(f"Not a git repository: {err.strip() or resolved}")
    rc_b, branch, _ = await _run_git(resolved, "rev-parse", "--abbrev-ref", "HEAD")
    branch_name = branch.strip() if rc_b == 0 and branch.strip() and branch.strip() != "HEAD" else "main"
    return {"repo_path": str(Path(top.strip()).resolve()), "base_branch": branch_name}


async def _find_branch_worktree(repo_path: Path, branch_name: str) -> Path | None:
    """Return the worktree path if `branch_name` is currently checked out anywhere."""
    rc, out, _ = await _run_git(repo_path, "worktree", "list", "--porcelain")
    if rc != 0:
        return None
    target_ref = f"refs/heads/{branch_name}"
    current_wt: str | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            current_wt = line.removeprefix("worktree ").strip()
        elif line.startswith("branch ") and line.removeprefix("branch ").strip() == target_ref and current_wt:
            return Path(current_wt).resolve()
        elif not line.strip():
            current_wt = None
    return None


async def create_worktree(repo_path: Path, base_branch: str, worktree_path: Path, branch_name: str) -> Path:
    """Create an isolated git worktree + branch at an absolute path for one Captain worker task."""
    repo_path = repo_path.expanduser().resolve()
    worktree_path = worktree_path.expanduser().resolve()
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists():
        await _run_git(repo_path, "worktree", "remove", "--force", str(worktree_path))
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
    await _run_git(repo_path, "worktree", "prune")

    # If this branch is still checked out in a stale/different worktree, detach it first.
    existing_wt = await _find_branch_worktree(repo_path, branch_name)
    if existing_wt and existing_wt != repo_path:
        await _run_git(repo_path, "worktree", "remove", "--force", str(existing_wt))
        if existing_wt.exists():
            shutil.rmtree(existing_wt, ignore_errors=True)
        await _run_git(repo_path, "worktree", "prune")

    # Verify base_branch exists; fall back to HEAD if needed.
    ref = base_branch or "HEAD"
    rc_ref, _, _ = await _run_git(repo_path, "rev-parse", "--verify", ref)
    if rc_ref != 0:
        ref = "HEAD"

    # If branch already exists (e.g. retry), reuse it; otherwise create from ref.
    rc_br, _, _ = await _run_git(repo_path, "rev-parse", "--verify", f"refs/heads/{branch_name}")
    if rc_br == 0:
        rc, _, err = await _run_git(repo_path, "worktree", "add", str(worktree_path), branch_name)
    else:
        rc, _, err = await _run_git(repo_path, "worktree", "add", "-b", branch_name, str(worktree_path), ref)
    if rc != 0:
        raise GitError(f"Failed to create git worktree: {err.strip()}")
    return worktree_path


async def get_worktree_diff(worktree_path: Path, base_branch: str = "HEAD") -> tuple[str, str]:
    """Return (diff_stat, unified_diff) including staged, unstaged, and untracked changes."""
    worktree_path = worktree_path.expanduser().resolve()
    if not worktree_path.exists():
        return "", ""
    _, status_out, _ = await _run_git(worktree_path, "status", "--short")
    # Compare working tree against base_branch if available, else HEAD.
    rc_ref, _, _ = await _run_git(worktree_path, "rev-parse", "--verify", base_branch)
    ref = base_branch if rc_ref == 0 else "HEAD"
    _, stat_out, _ = await _run_git(worktree_path, "diff", "--stat", ref)
    _, diff_out, _ = await _run_git(worktree_path, "diff", ref)

    untracked = [line[3:] for line in status_out.splitlines() if line.startswith("?? ")]
    stat_parts = [stat_out.strip()] if stat_out.strip() else []
    if untracked:
        stat_parts.append("Untracked files:\n" + "\n".join(f"  + {f}" for f in untracked[:50]))
    diff_parts = [diff_out.strip()] if diff_out.strip() else []
    for rel in untracked[:20]:
        f = worktree_path / rel
        if f.is_file() and f.stat().st_size <= 32_000:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                diff_parts.append(f"--- /dev/null\n+++ b/{rel}\n" + "\n".join(f"+{ln}" for ln in content.splitlines()))
            except OSError:
                pass
    full_diff = "\n\n".join(diff_parts)
    if len(full_diff) > 120_000:
        full_diff = full_diff[:120_000] + "\n... (diff truncated)"
    return "\n".join(stat_parts), full_diff


async def remove_worktree(
    repo_path: Path,
    worktree_path: Path,
    branch_name: str | None = None,
    delete_branch: bool = False,
) -> None:
    """Safely remove a task's git worktree (and optionally its local branch)."""
    repo_path = repo_path.expanduser().resolve()
    worktree_path = worktree_path.expanduser().resolve()
    if worktree_path.exists():
        await _run_git(repo_path, "worktree", "remove", "--force", str(worktree_path))
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
    await _run_git(repo_path, "worktree", "prune")
    if delete_branch and branch_name:
        await _run_git(repo_path, "branch", "-D", branch_name)


async def collect_repo_context(repo_path: Path) -> str:
    """Collect a bounded repository summary for Captain planning prompts."""
    parts: list[str] = []
    rc, files_out, _ = await _run_git(repo_path, "ls-files")
    if rc == 0 and files_out.strip():
        lines = files_out.strip().splitlines()
        sample = lines[:80]
        extra = f"\n... (+{len(lines) - 80} more files)" if len(lines) > 80 else ""
        parts.append("Tracked files:\n" + "\n".join(sample) + extra)

    _, status_out, _ = await _run_git(repo_path, "status", "--short")
    if status_out.strip():
        parts.append("Working tree status:\n" + status_out.strip()[:1000])

    for doc_name in ("CLAUDE.md", "AGENTS.md", "README.md"):
        doc = repo_path / doc_name
        if doc.is_file():
            try:
                text = doc.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    parts.append(f"{doc_name} (excerpt):\n{text[:2000]}")
            except OSError:
                pass

    combined = "\n\n".join(parts)
    return combined[:8000]
