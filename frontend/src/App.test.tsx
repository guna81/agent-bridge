import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { admin, getToken, setToken } from "./api";

vi.mock("./api", () => {
  let token = "test-admin-token";
  return {
    admin: vi.fn(),
    ApiError: class ApiError extends Error {
      status: number;
      constructor(status: number, message: string) {
        super(message);
        this.status = status;
      }
    },
    getToken: vi.fn(() => token),
    setToken: vi.fn((next: string) => { token = next; }),
    streamAdminEvents: vi.fn(() => new Promise(() => {})),
  };
});

vi.mock("./pages/Overview", () => ({ default: () => <div>Overview page</div> }));
vi.mock("./pages/Captain", () => ({ default: () => <div>Captain page</div> }));
vi.mock("./pages/Providers", () => ({ default: () => <div>Providers page</div> }));
vi.mock("./pages/Keys", () => ({ default: ({ usageOnly }: { usageOnly?: boolean }) => <div>{usageOnly ? "Request usage page" : "Keys & users page"}</div> }));
vi.mock("./pages/Playground", () => ({ default: () => <div>Playground page</div> }));
vi.mock("./pages/QuickStart", () => ({ default: () => <div>Quick start page</div> }));
vi.mock("./pages/StatusBarSettings", () => ({ default: () => <div>Status indicator page</div> }));
vi.mock("./pages/SubscriptionUsage", () => ({ default: () => <div>Subscription usage page</div> }));
vi.mock("./pages/Skills", () => ({ default: () => <div>Skills page</div> }));

const settings = {
  single_user_personal_use: true,
  allow_agent_mode: false,
  queue: { running: 0, waiting: 0, max_concurrency: 4 },
};

beforeEach(() => {
  window.scrollTo = vi.fn();
  window.location.hash = "";
  setToken("test-admin-token");
  vi.mocked(getToken).mockReturnValue("test-admin-token");
  vi.mocked(admin).mockImplementation(async (_method, path) => {
    if (path === "/settings") return settings;
    if (path === "/update-status") return { current: "0.3.7", latest: null, available: false, release_url: "" };
    return {};
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("groups proxy pages under the CLI proxy sidebar section", async () => {
  render(<App />);
  await screen.findByText("Overview page");

  const sideNav = screen.getByRole("navigation", { name: "Sections" });
  expect(within(sideNav).getByText("CLI proxy")).toBeInTheDocument();
  expect(within(sideNav).getByRole("button", { name: "Providers" })).toBeInTheDocument();
  expect(within(sideNav).getByRole("button", { name: "Keys & users" })).toBeInTheDocument();
  expect(within(sideNav).getByRole("button", { name: "Request usage" })).toBeInTheDocument();
  expect(within(sideNav).getByRole("button", { name: "Playground" })).toBeInTheDocument();
  expect(within(sideNav).getByRole("button", { name: "Quick start" })).toBeInTheDocument();

  fireEvent.click(within(sideNav).getByRole("button", { name: "Keys & users" }));
  expect(screen.getByText("Keys & users page")).toBeInTheDocument();
  expect(window.location.hash).toBe("#keys");
  expect(within(sideNav).getByRole("button", { name: "Keys & users" })).toHaveAttribute("aria-current", "page");
});

it("supports #cliproxy and existing proxy hashes", async () => {
  window.location.hash = "#cliproxy";
  render(<App />);
  await screen.findByText("Providers page");

  window.location.hash = "#quickstart";
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(await screen.findByText("Quick start page")).toBeInTheDocument();
});
