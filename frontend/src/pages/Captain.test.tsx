import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import Captain from "./Captain";
import { admin } from "../api";

vi.mock("../api", async (orig) => {
  const actual = await orig<typeof import("../api")>();
  return {
    ...actual,
    admin: vi.fn(),
    streamAdminEvents: vi.fn(() => new Promise(() => {})),
  };
});

const mockProjects = [
  {
    id: 1,
    name: "AgentBridge",
    slug: "agentbridge",
    repo_path: "/tmp/repo",
    base_branch: "main",
    captain_provider: "claude",
    captain_model: "sonnet",
    approval_mode: "manual" as const,
    allowed_providers: [],
    agent_roles: { claude: "backend", codex: "tests" },
    instructions: "",
    max_budget_usd: null,
    webhook_url: "",
    webhook_events: ["awaiting_approval", "needs_input", "completed", "failed"],
    active_missions: 1,
    total_missions: 1,
    created_at: "2026-11-26T00:00:00+00:00",
    updated_at: "2026-11-26T00:00:00+00:00",
  },
];

const mockProviders = [
  { name: "claude", kind: "claude", enabled: true, default_model: "sonnet", models: ["sonnet"], backend: "cli", binary_path: "", mode: "raw", auth_mode: "api_key", raw_system_prompt: "", skip_permissions: false, use_host_home: false, max_budget_usd: null, extra: {}, has_api_key: true },
  { name: "codex", kind: "codex", enabled: true, default_model: "default", models: ["default"], backend: "cli", binary_path: "", mode: "raw", auth_mode: "api_key", raw_system_prompt: "", skip_permissions: false, use_host_home: false, max_budget_usd: null, extra: {}, has_api_key: true },
];

const mockMission = {
  id: "m123",
  project_id: 1,
  title: "Add dark mode",
  goal: "Add dark mode and tests",
  status: "awaiting_approval" as const,
  captain_provider: "claude",
  captain_model: "sonnet",
  plan_summary: "Two parallel tasks",
  final_summary: "",
  error: "",
  created_at: "2026-11-26T00:00:00+00:00",
  updated_at: "2026-11-26T00:00:00+00:00",
  completed_at: null,
  tasks: [
    {
      id: 10,
      mission_id: "m123",
      order_index: 0,
      title: "Update CSS tokens",
      description: "Add dark variables",
      provider_name: "claude",
      model: "sonnet",
      rationale: "UI specialist",
      status: "pending" as const,
      worktree_path: "",
      branch_name: "",
      diff_stat: "",
      output_text: "",
      error: "",
      cost_usd: 0,
      duration_ms: null,
      created_at: "2026-11-26T00:00:00+00:00",
      started_at: null,
      completed_at: null,
    },
  ],
  messages: [
    {
      id: 1,
      mission_id: "m123",
      task_id: null,
      sender_type: "user" as const,
      sender_name: "You",
      channel: "dashboard",
      kind: "order" as const,
      content: "Add dark mode and tests",
      meta: {},
      created_at: "2026-11-26T00:00:00+00:00",
    },
  ],
};

beforeEach(() => {
  vi.mocked(admin).mockImplementation(async (method, path) => {
    if (method === "GET" && path === "/projects") return mockProjects;
    if (method === "GET" && path === "/providers") return mockProviders;
    if (method === "GET" && path === "/projects/1/missions") return [mockMission];
    if (method === "GET" && path === "/missions/m123") return mockMission;
    if (method === "POST" && path === "/missions/m123/approve") return { ...mockMission, status: "running" };
    return {};
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("renders project missions and approves a planned mission", async () => {
  render(<Captain go={() => {}} />);

  expect(await screen.findByText("Update CSS tokens")).toBeInTheDocument();
  const approveBtn = screen.getByRole("button", { name: /Approve & Run Tasks/i });
  fireEvent.click(approveBtn);

  await waitFor(() => {
    expect(admin).toHaveBeenCalledWith("POST", "/missions/m123/approve", {});
  });
});

it("shows project validation errors inside the modal", async () => {
  vi.mocked(admin).mockImplementation(async (method, path) => {
    if (method === "GET" && path === "/projects") return mockProjects;
    if (method === "GET" && path === "/providers") return mockProviders;
    if (method === "GET" && path === "/projects/1/missions") return [mockMission];
    if (method === "GET" && path === "/missions/m123") return mockMission;
    if (method === "POST" && path === "/projects") throw new Error("Repository path does not exist");
    return {};
  });

  render(<Captain go={() => {}} />);
  expect(await screen.findByText("Update CSS tokens")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "+ New project" }));
  fireEvent.change(screen.getByPlaceholderText("e.g. AgentBridge"), { target: { value: "BadRepo" } });
  fireEvent.change(screen.getByPlaceholderText("/Users/you/code/my-repo"), { target: { value: "/tmp/nope" } });
  fireEvent.click(screen.getByRole("button", { name: "Create project" }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Repository path does not exist");
  expect(alert.closest(".modal-card")).not.toBeNull();
});
