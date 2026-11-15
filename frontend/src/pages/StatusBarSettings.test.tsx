import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import StatusBarSettings from "./StatusBarSettings";
import { admin } from "../api";
vi.mock("../api", () => ({ admin: vi.fn() }));
const config = { indicator_enabled: true, enabled_providers: { codex: true, claude: true, antigravity: true }, selected_clis: ["codex"], display_mode: "bars", refresh_interval_seconds: 5, pinned_metric: "codex_5h" };
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it("loads and saves indicator changes", async () => {
  vi.mocked(admin).mockResolvedValueOnce(config).mockResolvedValueOnce({ ...config, indicator_enabled: false });
  render(<StatusBarSettings />);
  fireEvent.click(await screen.findByRole("switch"));
  fireEvent.change(screen.getByLabelText("Refresh interval"), { target: { value: "10" } });
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await screen.findByText("Settings saved.", { exact: false });
  expect(admin).toHaveBeenLastCalledWith("POST", "/status-bar/config", expect.objectContaining({ indicator_enabled: false, refresh_interval_seconds: 10, selected_clis: ["codex"] }));
});
it("shows load failures", async () => {
  vi.mocked(admin).mockRejectedValueOnce(new Error("Cannot load settings"));
  render(<StatusBarSettings />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Cannot load settings");
});
it("shows save failures and permits retry", async () => {
  vi.mocked(admin).mockResolvedValueOnce(config).mockRejectedValueOnce(new Error("Save failed"));
  render(<StatusBarSettings />);
  const save = await screen.findByRole("button", { name: "Save settings" });
  fireEvent.click(save);
  expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
  await waitFor(() => expect(save).toBeEnabled());
  expect(screen.queryByText("Settings saved.", { exact: false })).toBeNull();
});
it("keeps one or two indicator agents selected", async () => {
  vi.mocked(admin).mockResolvedValueOnce(config);
  render(<StatusBarSettings />);
  const codex = await screen.findByLabelText("Codex");
  expect(codex).toBeDisabled();
  fireEvent.click(screen.getByLabelText("Antigravity"));
  expect(codex).toBeEnabled();
  expect(screen.getAllByLabelText("Claude Code")[1]).toBeDisabled();
});
