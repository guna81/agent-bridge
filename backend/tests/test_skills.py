from pathlib import Path

import httpx
import pytest

from app.skills import SkillsError, SkillsRepo, parse_frontmatter, skills_home

SKILL = """---
name: review-code
description: >-
  Review code changes for bugs.
  Use when the user asks for a code review.
---

# Code Review

Find real problems.
"""


def wrapper(repo: SkillsRepo, name="code-reviewer", skill="review-code", tools="tools: Read, Grep\n") -> str:
    return (f"---\nname: {name}\ndescription: Reviews code.\n{tools}---\n\n"
            f"Read {repo.skills_dir / skill / 'SKILL.md'} and follow it exactly.\n")


@pytest.fixture
def repo(tmp_path: Path) -> SkillsRepo:
    r = SkillsRepo(tmp_path / "agents", home=tmp_path / "home", codex_home=tmp_path / "home" / ".codex")
    (r.skills_dir / "review-code").mkdir(parents=True)
    (r.skills_dir / "review-code" / "SKILL.md").write_text(SKILL)
    r.wrappers_dir.mkdir(parents=True)
    (r.wrappers_dir / "code-reviewer.md").write_text(wrapper(r))
    return r


def messages(issues):
    return [i["message"] for i in issues]


def test_parse_frontmatter_block_and_quoted_values():
    fm, body, err = parse_frontmatter(SKILL)
    assert err is None
    assert fm["description"] == "Review code changes for bugs. Use when the user asks for a code review."
    assert body.strip().startswith("# Code Review")
    fm, _, _ = parse_frontmatter('---\nname: x\ndescription: "a: b"\n---\n')
    assert fm["description"] == "a: b"
    assert parse_frontmatter("# no frontmatter")[2]
    assert parse_frontmatter("---\nname: x\n")[2]


def test_clean_repo_has_no_errors_and_reports_unlinked(repo):
    st = repo.state()
    [skill] = st["skills"]
    assert skill["issues"] == []
    assert skill["wrappers"] == ["code-reviewer"]
    assert set(skill["linked"].values()) == {"missing"}
    [w] = st["wrappers"]
    assert w["skill"] == "review-code" and w["issues"] == [] and w["linked"] == "missing"


def test_skill_validation_catches_rule_breaks(repo):
    bad = SKILL.replace("name: review-code", "name: review-codez")
    assert any("doesn't match the folder" in m for m in messages(repo.validate_skill("review-code", bad)))
    no_when = SKILL.replace("  Use when the user asks for a code review.\n", "")
    assert any("Use when" in m for m in messages(repo.validate_skill("review-code", no_when)))
    long_desc = SKILL.replace("Review code changes for bugs.", "x" * 1100)
    assert any("limit 1024" in m for m in messages(repo.validate_skill("review-code", long_desc)))
    builtin = SKILL.replace("review-code", "code-review")
    (repo.skills_dir / "code-review").mkdir()
    assert any("built-in" in m for m in messages(repo.validate_skill("code-review", builtin)))
    # every skill needs a wrapper
    (repo.wrappers_dir / "code-reviewer.md").unlink()
    assert any("No Claude Code wrapper" in m for m in messages(next(s for s in repo.state()["skills"] if s["name"] == "review-code")["issues"]))


def test_wrapper_must_use_absolute_existing_path(repo):
    rel = "---\nname: code-reviewer\ndescription: d\n---\nRead agents/skills/review-code/SKILL.md\n"
    issues, skill = repo.validate_wrapper("code-reviewer", rel)
    assert skill is None and any("absolute path" in m for m in messages(issues))
    missing, skill = repo.validate_wrapper("code-reviewer", wrapper(repo, skill="nope"))
    assert any("does not exist" in m for m in messages(missing))
    no_tools, _ = repo.validate_wrapper("code-reviewer", wrapper(repo, tools=""))
    assert [i["level"] for i in no_tools] == ["info"]


def test_save_rejects_stale_base_and_bad_names(repo):
    path = repo.skills_dir / "review-code" / "SKILL.md"
    repo.save("skill", "review-code", SKILL + "\nMore.\n", base=SKILL)
    assert path.read_text().endswith("More.\n")
    with pytest.raises(SkillsError, match="changed on disk"):
        repo.save("skill", "review-code", "x", base=SKILL)
    with pytest.raises(SkillsError):
        repo.save("skill", "../etc", "x")
    with pytest.raises(SkillsError):
        repo.save("wrapper", "missing", "x")


def test_create_writes_skill_and_wrapper_with_absolute_path(repo):
    repo.create("write-docs", "Write docs. Use when asked to document: e.g. a README.", "doc-writer", "Read, Edit")
    st = repo.state()
    skill = next(s for s in st["skills"] if s["name"] == "write-docs")
    assert skill["issues"] == [] and skill["wrappers"] == ["doc-writer"]
    w = next(x for x in st["wrappers"] if x["name"] == "doc-writer")
    assert w["issues"] == [] and str(repo.skills_dir / "write-docs" / "SKILL.md") in w["text"]
    with pytest.raises(SkillsError, match="already exists"):
        repo.create("write-docs", "d", None)
    with pytest.raises(SkillsError, match="already exists"):
        repo.create("other", "d", "doc-writer")


def test_link_all_matches_install_sh_rules(repo):
    targets = repo.target_dirs()
    # a real folder in the way is skipped, a stale symlink is replaced
    (targets["agy"] / "review-code").mkdir(parents=True)
    targets["codex"].mkdir(parents=True)
    (targets["codex"] / "review-code").symlink_to(repo.root)
    results = {r["path"]: r["status"] for r in repo.link_all()}
    assert results[str(targets["claude"] / "review-code")] == "linked"
    assert results[str(targets["codex"] / "review-code")] == "relinked"
    assert results[str(targets["agy"] / "review-code")] == "skipped"
    assert results[str(repo.agents_link_dir / "code-reviewer.md")] == "linked"
    skill = repo.state()["skills"][0]
    assert skill["linked"] == {"claude": "linked", "codex": "linked", "agy": "conflict"}
    assert {r["status"] for r in repo.link_all() if "agy" not in r["path"] and ".gemini" not in r["path"]} == {"unchanged"}



def test_link_all_removes_links_to_renamed_skills(repo, tmp_path):
    targets = repo.target_dirs()
    repo.link_all()
    (repo.skills_dir / "review-code").rename(repo.skills_dir / "review-diff")
    other = tmp_path / "elsewhere"
    (targets["claude"] / "not-ours").symlink_to(other)  # broken, but not into this repo: left alone
    results = {r["path"]: r["status"] for r in repo.link_all()}
    for t in targets.values():
        assert results[str(t / "review-code")] == "removed" and not (t / "review-code").is_symlink()
        assert results[str(t / "review-diff")] == "linked"
    assert (targets["claude"] / "not-ours").is_symlink()

def test_skills_home_is_fixed_in_the_agentbridge_home(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTBRIDGE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert skills_home() == (tmp_path / ".agentbridge" / "agents").resolve()
    monkeypatch.setenv("AGENTBRIDGE_HOME", str(tmp_path / "ab"))
    assert skills_home() == (tmp_path / "ab" / "agents").resolve()


def test_skills_admin_endpoints(live):
    # The live server's skills dir is a temp folder (PROXY_SKILLS_DIR in conftest).
    st = live.admin("GET", "/skills")
    assert st["skills"] == [] and st["wrappers"] == []
    created = live.admin("POST", "/skills", json={
        "name": "write-docs", "description": "Write docs. Use when asked to document code.",
        "wrapper_name": "doc-writer", "link": False})
    assert created["links"] is None
    skill = next(s for s in created["state"]["skills"] if s["name"] == "write-docs")
    assert skill["issues"] == []

    v = live.admin("POST", "/skills/skill/write-docs/validate", json={"text": skill["text"].replace("name: write-docs", "name: nope")})
    assert any("doesn't match" in i["message"] for i in v["issues"])

    saved = live.admin("PUT", "/skills/skill/write-docs", json={"text": skill["text"] + "\nExtra.\n", "base": skill["text"]})
    assert next(s for s in saved["skills"] if s["name"] == "write-docs")["text"].endswith("Extra.\n")

    stale = httpx.put(live.base + "/admin/skills/skill/write-docs", headers={"Authorization": "Bearer test-admin-token"},
                      json={"text": "x", "base": skill["text"]})
    assert stale.status_code == 400 and "changed on disk" in stale.json()["error"]["message"]
    bad = httpx.put(live.base + "/admin/skills/skill/Bad_Name", headers={"Authorization": "Bearer test-admin-token"}, json={"text": "x"})
    assert bad.status_code == 400
    assert httpx.get(live.base + "/admin/skills").status_code == 401

    # The folder is fixed: there is no endpoint to change or browse for it.
    assert "default_root" not in st
    from app.api.admin import router
    assert not [r.path for r in router.routes if "folder" in r.path]


def write_instr(repo: SkillsRepo, name: str, text: str) -> None:
    repo.instructions_dir.mkdir(parents=True, exist_ok=True)
    repo.instruction_file(name).write_text(text)


def test_instructions_combine_global_and_agent_and_keep_user_content(repo):
    write_instr(repo, "global", "# Shared\n\nBe brief.\n")
    write_instr(repo, "codex", "Use pnpm.\n")
    claude_md = repo.instruction_targets()["claude"]
    claude_md.parent.mkdir(parents=True)
    claude_md.write_text("My own notes.\n")

    assert {t["id"]: t["status"] for t in repo.state()["instructions"]["targets"]} == {"claude": "missing", "codex": "missing", "agy": "missing"}
    results = repo.apply_instructions()
    assert [r["status"] for r in results] == ["added", "added", "added"]

    claude = claude_md.read_text()
    assert claude.startswith("My own notes.\n\n<!-- BEGIN AgentBridge instructions sha256:")
    assert "# Shared\n\nBe brief.\n<!-- END" in claude and "pnpm" not in claude
    codex = repo.instruction_targets()["codex"].read_text()
    assert "Be brief.\n\nUse pnpm.\n<!-- END AgentBridge instructions -->" in codex
    st = {t["id"]: t for t in repo.state()["instructions"]["targets"]}
    assert st["claude"] == {**st["claude"], "status": "applied", "own_lines": 1}
    assert [r["status"] for r in repo.apply_instructions()] == ["unchanged"] * 3

    # Saving a source file keeps agents that already use the block in sync, and leaves the user's text alone.
    repo.save("instructions", "global", "Be very brief.\n", base="# Shared\n\nBe brief.\n")
    assert repo.state()["instructions"]["targets"][0]["status"] == "applied"
    assert claude_md.read_text().startswith("My own notes.\n\n") and "Be very brief." in claude_md.read_text()

    # Removing takes out only the block.
    assert repo.remove_instructions("claude")["status"] == "removed"
    assert claude_md.read_text() == "My own notes.\n"


def test_hand_edited_block_needs_force_and_is_not_synced(repo):
    write_instr(repo, "global", "Rule one.\n")
    repo.apply_instructions(["agy"])
    gemini = repo.instruction_targets()["agy"]
    gemini.write_text(gemini.read_text().replace("Rule one.", "Rule one, edited by hand."))
    assert repo.target_status("agy")["status"] == "edited"

    repo.save("instructions", "global", "Rule two.\n")
    assert "edited by hand" in gemini.read_text()
    assert repo.apply_instructions(["agy"])[0]["status"] == "skipped"
    assert repo.apply_instructions(["agy"], force=True)[0]["status"] == "updated"
    assert "Rule two." in gemini.read_text() and repo.target_status("agy")["status"] == "applied"


def test_empty_instructions_never_overwrite_a_block_from_another_folder(repo, tmp_path):
    # Another AgentBridge (say, the installed copy) wrote rules into the same agent files.
    other = SkillsRepo(tmp_path / "installed", home=repo.home, codex_home=repo.codex_home)
    write_instr(other, "global", "Keep my rules.\n")
    other.apply_instructions()
    claude_md = repo.instruction_targets()["claude"]
    before = claude_md.read_text()

    st = repo.target_status("claude")
    assert st["status"] == "outdated" and st["source"] == str(other.instructions_dir)
    assert other.target_status("claude")["source"] == str(other.instructions_dir)

    # This folder has nothing to say, so Link leaves the block alone, even when forced.
    for force in (False, True):
        results = repo.apply_instructions(force=force)
        assert {r["status"] for r in results} == {"skipped"} and "empty" in results[0]["detail"]
    assert claude_md.read_text() == before

    # Once there is something to link, Link replaces the block and it now comes from here.
    write_instr(repo, "global", "New rules.\n")
    assert repo.apply_instructions(["claude"])[0]["status"] == "updated"
    assert "New rules." in claude_md.read_text() and "Keep my rules." not in claude_md.read_text()
    assert repo.target_status("claude")["source"] == str(repo.instructions_dir)


def test_instructions_validation_and_names(repo):
    assert "Empty" in messages(repo.validate("instructions", "global", "")["issues"])[0]
    issues = repo.validate("instructions", "global", "x\n<!-- END AgentBridge instructions -->\n")["issues"]
    assert any(i["level"] == "error" for i in issues)
    with pytest.raises(SkillsError):
        repo.save("instructions", "global", "<!-- END AgentBridge instructions -->")
    with pytest.raises(SkillsError):
        repo.save("instructions", "cursor", "x")
    with pytest.raises(SkillsError):
        repo.save("instructions", "global", "x", base="stale")


def test_instructions_follow_a_symlinked_target(repo, tmp_path):
    real = tmp_path / "dotfiles" / "AGENTS.md"
    real.parent.mkdir()
    real.write_text("Mine.\n")
    link = repo.instruction_targets()["codex"]
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    write_instr(repo, "global", "Shared.\n")
    repo.apply_instructions(["codex"])
    assert link.is_symlink() and "Shared." in real.read_text()


def test_instructions_admin_endpoints(live):
    st = live.admin("GET", "/skills")["instructions"]
    assert [f["name"] for f in st["files"]] == ["global", "claude", "codex", "agy"]
    assert all(t["status"] == "missing" for t in st["targets"])
    saved = live.admin("PUT", "/skills/instructions/global", json={"text": "Shared rule.\n", "base": ""})
    assert saved["instructions"]["files"][0]["text"] == "Shared rule.\n"
    applied = live.admin("POST", "/skills/instructions/apply", json={"targets": ["codex"]})
    assert applied["results"][0]["status"] == "added"
    target = next(t for t in applied["state"]["instructions"]["targets"] if t["id"] == "codex")
    # The test server's agents home is a temp folder, never the real ~/.codex.
    assert target["status"] == "applied" and "proxy-test-" in target["path"]
    removed = live.admin("POST", "/skills/instructions/remove", json={"target": "codex"})
    assert removed["results"][0]["status"] == "removed"
    bad = httpx.post(live.base + "/admin/skills/instructions/remove", headers={"Authorization": "Bearer test-admin-token"}, json={"target": "nope"})
    assert bad.status_code == 400


def test_saving_one_agents_instructions_leaves_other_agents_alone(repo):
    write_instr(repo, "global", "Be brief.\n")
    repo.apply_instructions(["claude"])
    write_instr(repo, "global", "Be brief. Use pnpm.\n")  # changed outside the dashboard
    assert repo.target_status("claude")["status"] == "outdated"
    repo.save("instructions", "codex", "Codex only.\n", base="")
    assert repo.target_status("claude")["status"] == "outdated"
    assert "Use pnpm." not in repo.instruction_targets()["claude"].read_text()


def test_apply_skips_agents_with_nothing_to_receive(repo):
    write_instr(repo, "claude", "Claude only.\n")
    results = repo.apply_instructions()
    assert [r["status"] for r in results] == ["added", "unchanged", "unchanged"]
    assert not repo.instruction_targets()["codex"].exists()
    assert not repo.instruction_targets()["agy"].exists()


def test_wrapper_in_a_folder_with_spaces_finds_its_skill(tmp_path):
    r = SkillsRepo(tmp_path / "My Projects" / "agents", home=tmp_path / "home", codex_home=tmp_path / "home" / ".codex")
    r.skills_dir.mkdir(parents=True)
    r.create("demo", "Demo. Use when testing.", "demo-agent")
    w = r.state()["wrappers"][0]
    assert w["skill"] == "demo"
    assert not [i for i in w["issues"] if i["level"] == "error"]


def test_link_and_unlink_one_skill_in_chosen_agents(repo, tmp_path):
    targets = repo.target_dirs()
    assert [r["status"] for r in repo.link_one("skill", "review-code", ["codex"])] == ["linked"]
    assert (targets["codex"] / "review-code").is_symlink() and not (targets["claude"] / "review-code").exists()
    results = {r["path"]: r["status"] for r in repo.link_one("skill", "review-code")}
    assert results[str(targets["codex"] / "review-code")] == "unchanged"
    assert results[str(targets["claude"] / "review-code")] == "linked"

    # Unlink removes only links that point at the skill.
    (targets["agy"] / "review-code").unlink()
    (targets["agy"] / "review-code").symlink_to(tmp_path)
    results = {r["path"]: r["status"] for r in repo.unlink_one("skill", "review-code")}
    assert results[str(targets["claude"] / "review-code")] == "removed"
    assert results[str(targets["codex"] / "review-code")] == "removed"
    assert results[str(targets["agy"] / "review-code")] == "skipped"
    assert (targets["agy"] / "review-code").is_symlink() and repo.skill_file("review-code").is_file()
    assert repo.unlink_one("skill", "review-code", ["claude"])[0]["status"] == "unchanged"

    (targets["claude"] / "review-code").mkdir()
    assert repo.unlink_one("skill", "review-code", ["claude"])[0]["status"] == "skipped"
    assert (targets["claude"] / "review-code").is_dir()


def test_link_and_unlink_one_wrapper_and_bad_requests(repo):
    dst = repo.agents_link_dir / "code-reviewer.md"
    assert repo.link_one("wrapper", "code-reviewer")[0]["status"] == "linked" and dst.is_symlink()
    assert repo.unlink_one("wrapper", "code-reviewer")[0]["status"] == "removed" and not dst.exists()
    with pytest.raises(SkillsError, match="Unknown agent"):
        repo.link_one("skill", "review-code", ["nope"])
    with pytest.raises(SkillsError, match="doesn't exist"):
        repo.unlink_one("skill", "missing-skill")
    with pytest.raises(SkillsError, match="doesn't exist"):
        repo.link_one("wrapper", "missing-wrapper")
    with pytest.raises(SkillsError, match="kind must be"):
        repo.link_one("instructions", "global")


def test_link_one_admin_endpoints(live):
    live.admin("POST", "/skills", json={"name": "lint-code", "description": "Lint code. Use when asked to lint.",
                                        "wrapper_name": "linter", "link": False})
    linked = live.admin("POST", "/skills/skill/lint-code/link", json={"targets": ["claude"]})
    assert [r["status"] for r in linked["links"]] == ["linked"] and "proxy-test-" in linked["links"][0]["path"]
    skill = next(s for s in linked["state"]["skills"] if s["name"] == "lint-code")
    assert skill["linked"] == {"claude": "linked", "codex": "missing", "agy": "missing"}
    unlinked = live.admin("POST", "/skills/skill/lint-code/unlink", json={})
    assert [r["status"] for r in unlinked["links"]] == ["removed", "unchanged", "unchanged"]
    wrapped = live.admin("POST", "/skills/wrapper/linter/link", json={})
    assert next(w for w in wrapped["state"]["wrappers"] if w["name"] == "linter")["linked"] == "linked"
    live.admin("POST", "/skills/wrapper/linter/unlink", json={})
    bad = httpx.post(live.base + "/admin/skills/skill/lint-code/link", headers={"Authorization": "Bearer test-admin-token"}, json={"targets": ["nope"]})
    assert bad.status_code == 400
