import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import Skills from "./Skills";
import { admin, InstructionFile, InstructionStatus, SkillsState } from "../api";
vi.mock("../api", () => ({ admin: vi.fn() }));

const SKILL = "---\nname: review-code\ndescription: >-\n  Review code. Use when asked.\n---\n\n# Code Review\n\n- Find bugs\n";
const state = (text = SKILL): SkillsState => ({
  root: "/repo/agents",
  skills_dir: "/repo/agents/skills",
  wrappers_dir: "/repo/agents/claude-agents",
  exists: true,
  targets: [{ id: "claude", label: "Claude Code", dir: "/h/.claude/skills" }, { id: "codex", label: "Codex", dir: "/h/.codex/skills" }, { id: "agy", label: "Antigravity", dir: "/h/.gemini/config/skills" }],
  agents_dir: "/h/.claude/agents",
  skills: [{ kind: "skill", name: "review-code", path: "/repo/agents/skills/review-code/SKILL.md", text, linked: { claude: "linked", codex: "linked", agy: "missing" }, wrappers: ["code-reviewer"], files: [], issues: [] }],
  wrappers: [{ kind: "wrapper", name: "code-reviewer", path: "/repo/agents/claude-agents/code-reviewer.md", text: "---\nname: code-reviewer\n---\n", skill: "review-code", linked: "linked", issues: [] }],
  instructions: instr(),
});
function instr(global = "", codex = "", status: InstructionStatus = "missing"): SkillsState["instructions"] {
  const file = (name: InstructionFile["name"], label: string, text = "") => ({ kind: "instructions" as const, name, label, path: `/repo/agents/instructions/${name}.md`, text, issues: [] });
  return {
    dir: "/repo/agents/instructions",
    files: [file("global", "All agents", global), file("claude", "Claude Code"), file("codex", "Codex", codex), file("agy", "Antigravity")],
    targets: [
      { id: "claude", label: "Claude Code", path: "/h/.claude/CLAUDE.md", status, own_lines: 2 },
      { id: "codex", label: "Codex", path: "/h/.codex/AGENTS.md", status, own_lines: 0 },
      { id: "agy", label: "Antigravity", path: "/h/.gemini/GEMINI.md", status: "edited", own_lines: 0 },
    ],
  };
}
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("edits, live-validates, diffs and saves a skill", async () => {
  const edited = SKILL.replace("name: review-code", "name: oops");
  vi.mocked(admin).mockImplementation(async (method, path) => {
    if (method === "GET") return state();
    if (path.endsWith("/validate")) return { issues: [{ level: "error", message: "`name: oops` doesn't match the folder name `review-code`." }] };
    if (method === "PUT") return state(edited);
    throw new Error(`unexpected ${method} ${path}`);
  });
  render(<Skills />);
  expect(await screen.findByText("Antigravity: not linked")).toBeInTheDocument();
  const editor = screen.getByLabelText("Contents of review-code");
  fireEvent.change(editor, { target: { value: edited } });
  expect(await screen.findByText("doesn't match the folder name", { exact: false })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: /Changes/ }));
  expect(within(document.querySelector<HTMLElement>(".skills-diff")!).getByText("name: oops")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Changes (2)" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Saved review-code", { exact: false });
  expect(admin).toHaveBeenCalledWith("PUT", "/skills/skill/review-code", { text: edited, base: SKILL });
});

it("renders the preview with frontmatter fields", async () => {
  vi.mocked(admin).mockResolvedValueOnce(state());
  render(<Skills />);
  fireEvent.click(await screen.findByRole("tab", { name: "Preview" }));
  expect(screen.getByText("Review code. Use when asked.", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Code Review" })).toBeInTheDocument();
  expect(screen.getByText("Find bugs")).toBeInTheDocument();
});

it("creates a skill with a wrapper and links it", async () => {
  vi.mocked(admin).mockImplementation(async (method) => {
    if (method === "GET") return state();
    return { links: [{ path: "/h/.claude/skills/write-docs", status: "linked" }], state: state() };
  });
  render(<Skills />);
  fireEvent.click(await screen.findByRole("button", { name: "New skill" }));
  fireEvent.change(screen.getByLabelText("Skill name", { exact: false }), { target: { value: "write-docs" } });
  fireEvent.change(screen.getByLabelText("Description", { exact: false }), { target: { value: "Write docs. Use when asked." } });
  expect(screen.getByLabelText("Wrapper name", { exact: false })).toHaveValue("write-docs-agent");
  fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
  await screen.findByText("1 links created or updated.", { exact: false });
  expect(admin).toHaveBeenCalledWith("POST", "/skills", expect.objectContaining({ name: "write-docs", wrapper_name: "write-docs-agent", link: true }));
});

it("shows load failures", async () => {
  vi.mocked(admin).mockRejectedValueOnce(new Error("Skills unavailable"));
  render(<Skills />);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Skills unavailable"));
});

it("shows the fixed skills folder with no way to change it", async () => {
  vi.mocked(admin).mockImplementation(async (method) => {
    if (method === "GET") {
      const a = "/home/alice/.agentbridge/agents";
      return { ...state(), root: a, skills_dir: `${a}/skills`, wrappers_dir: `${a}/claude-agents`, user_home: "/home/alice",
        instructions: { ...instr(), dir: `${a}/instructions` } };
    }
    throw new Error(`unexpected ${method}`);
  });
  render(<Skills />);
  // Both folders the Skills page edits, with the home folder shortened to ~ and the full path on hover.
  expect(await screen.findByText("~/.agentbridge/agents/skills")).toHaveAttribute("title", "/home/alice/.agentbridge/agents/skills");
  expect(screen.getByText("~/.agentbridge/agents/claude-agents")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Change folder|Browse/ })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Skills folder")).not.toBeInTheDocument();
  cleanup();

  render(<Skills mode="instructions" />);
  expect(await screen.findByText("~/.agentbridge/agents/instructions")).toBeInTheDocument();
});

it("picks up changes made on disk and warns when they clash with unsaved edits", async () => {
  let disk = SKILL;
  vi.mocked(admin).mockImplementation(async () => state(disk));
  render(<Skills />);
  const editor = await screen.findByLabelText("Contents of review-code");
  disk = SKILL + "- Check tests\n";
  fireEvent.focus(window);
  await waitFor(() => expect(editor).toHaveValue(disk));

  fireEvent.change(editor, { target: { value: disk + "- Mine\n" } });
  disk = SKILL + "- Someone else\n";
  fireEvent.focus(window);
  expect(await screen.findByText("changed on disk while you were editing", { exact: false })).toBeInTheDocument();
  expect(editor).toHaveValue(SKILL + "- Check tests\n- Mine\n");
});

it("edits global instructions, previews what one agent gets, and links them", async () => {
  let current = { ...state(), instructions: instr("", "Use pnpm.\n") };
  vi.mocked(admin).mockImplementation(async (method, path, body) => {
    if (method === "GET") return current;
    if (path.endsWith("/validate")) return { issues: [] };
    if (method === "PUT") { current = { ...state(), instructions: instr((body as { text: string }).text, "Use pnpm.\n") }; return current; }
    if (path === "/skills/instructions/apply") {
      current = { ...state(), instructions: instr("Be brief.\n", "Use pnpm.\n", "applied") };
      return { results: [{ path: "/h/.claude/CLAUDE.md", status: "added" }, { path: "/h/.codex/AGENTS.md", status: "added" }], state: current };
    }
    throw new Error(`unexpected ${method} ${path}`);
  });
  render(<Skills mode="instructions" />);
  expect(await screen.findByRole("heading", { name: "Global instructions" })).toBeInTheDocument();
  expect(screen.queryByText("review-code")).not.toBeInTheDocument();
  expect(screen.getByText("Claude Code: not linked")).toBeInTheDocument();
  expect(screen.getByText("Antigravity: edited by hand")).toBeInTheDocument();
  expect(screen.getByText("plus 2 lines of your own", { exact: false })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Contents of global instructions"), { target: { value: "Be brief.\n" } });
  // Only Codex has anything saved to receive yet (an empty Claude Code block would be pointless), and edits must be saved first.
  expect(screen.getByRole("button", { name: "Link to Codex" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("Link to add it to Claude Code, Codex and Antigravity.", { exact: false })).toBeInTheDocument();
  expect(admin).toHaveBeenCalledWith("PUT", "/skills/instructions/global", { text: "Be brief.\n", base: "" });

  fireEvent.click(screen.getByRole("button", { name: "Link to Claude Code and Codex" }));
  expect(await screen.findByText("Linked the instructions to Claude Code and Codex.")).toBeInTheDocument();
  expect(admin).toHaveBeenCalledWith("POST", "/skills/instructions/apply", { targets: ["claude", "codex"], force: false });

  fireEvent.click(screen.getByRole("button", { name: "overwrite the block" }));
  await waitFor(() => expect(admin).toHaveBeenCalledWith("POST", "/skills/instructions/apply", { targets: ["agy"], force: true }));

  fireEvent.click(screen.getByRole("button", { name: /codex\.md/ }));
  fireEvent.click(screen.getByRole("tab", { name: "Preview" }));
  expect(screen.getByText("What Codex gets: the global instructions, then these.")).toBeInTheDocument();
  expect(screen.getByText("Be brief.")).toBeInTheDocument();
  expect(screen.getByText("Use pnpm.")).toBeInTheDocument();
});

it("saves once when ⌘S is pressed again while a save is in flight", async () => {
  const edited = SKILL + "- More\n";
  let finish: (s: SkillsState) => void = () => {};
  vi.mocked(admin).mockImplementation(async (method, path) => {
    if (method === "GET") return state();
    if (path.endsWith("/validate")) return { issues: [] };
    return new Promise<SkillsState>((resolve) => { finish = resolve; });
  });
  render(<Skills />);
  fireEvent.change(await screen.findByLabelText("Contents of review-code"), { target: { value: edited } });
  fireEvent.keyDown(document, { key: "s", metaKey: true });
  fireEvent.keyDown(document, { key: "s", metaKey: true });
  finish(state(edited));
  await screen.findByText("Saved review-code", { exact: false });
  expect(vi.mocked(admin).mock.calls.filter(([m]) => m === "PUT")).toHaveLength(1);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("doesn't let an unsaved skill edit block Link on the Instructions page", async () => {
  vi.mocked(admin).mockImplementation(async (method, path) => {
    if (method === "GET") return { ...state(), instructions: instr("Be brief.\n") };
    if (path.endsWith("/validate")) return { issues: [] };
    throw new Error(`unexpected ${method} ${path}`);
  });
  render(<Skills />);
  fireEvent.change(await screen.findByLabelText("Contents of review-code"), { target: { value: SKILL + "- Draft\n" } });
  expect(screen.getByText("1 unsaved")).toBeInTheDocument();
  cleanup();

  render(<Skills mode="instructions" />);
  expect(await screen.findByRole("button", { name: "Link to agents" })).toBeEnabled();
  expect(screen.queryByText("1 unsaved")).not.toBeInTheDocument();
  cleanup();

  // Drop the draft so it can't leak into other tests.
  render(<Skills />);
  fireEvent.click(await screen.findByRole("button", { name: "Revert" }));
});

it("links and unlinks one skill per agent", async () => {
  const after = state();
  after.skills[0].linked = { claude: "linked", codex: "missing", agy: "missing" };
  vi.mocked(admin).mockImplementation(async (method, path) => {
    if (method === "GET") return state();
    if (path.endsWith("/unlink")) return { links: [{ path: "/h/.codex/skills/review-code", status: "removed" }], state: after };
    if (path.endsWith("/link")) return { links: [{ path: "/h/.gemini/config/skills/review-code", status: "linked" }], state: state() };
    throw new Error(`unexpected ${method} ${path}`);
  });
  render(<Skills />);
  fireEvent.click(await screen.findByRole("button", { name: "Link to Antigravity" }));
  await screen.findByText("Linked review-code to Antigravity.");
  expect(admin).toHaveBeenCalledWith("POST", "/skills/skill/review-code/link", { targets: ["agy"] });

  fireEvent.click(screen.getByRole("button", { name: "Unlink from Codex" }));
  await screen.findByText("Unlinked review-code from Codex.");
  expect(admin).toHaveBeenCalledWith("POST", "/skills/skill/review-code/unlink", { targets: ["codex"] });
  expect(screen.getByRole("button", { name: "Link to Codex and Antigravity" })).toBeInTheDocument();
});

it("never offers to link empty instructions over a block written from another folder", async () => {
  const instructions = instr("", "", "outdated");
  instructions.targets = instructions.targets.map((t) => ({ ...t, status: "outdated" as const, source: "/home/.agentbridge/agents/instructions" }));
  vi.mocked(admin).mockImplementation(async (method) => {
    if (method === "GET") return { ...state(), instructions };
    throw new Error(`unexpected ${method}`);
  });
  render(<Skills mode="instructions" />);
  expect(await screen.findByText("Claude Code: linked from another folder")).toBeInTheDocument();
  expect(screen.getByText(/These blocks were written from \/home\/\.agentbridge\/agents\/instructions, not from this folder\. Nothing to link from here yet/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Link to/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Unlink from Codex" })).toBeEnabled();
});

it("shows a singular count and no link pill for an empty skills folder", async () => {
  vi.mocked(admin).mockImplementation(async (method) => {
    if (method === "GET") return { ...state(), skills: [], wrappers: [] };
    throw new Error(`unexpected ${method}`);
  });
  render(<Skills />);
  expect(await screen.findByText("0 skills · 0 wrappers")).toBeInTheDocument();
  expect(screen.queryByText("Linked in every agent")).not.toBeInTheDocument();
  cleanup();

  vi.mocked(admin).mockImplementation(async (method) => {
    if (method === "GET") return { ...state(), wrappers: [] };
    throw new Error(`unexpected ${method}`);
  });
  render(<Skills />);
  expect(await screen.findByText("1 skill · 0 wrappers")).toBeInTheDocument();
});
