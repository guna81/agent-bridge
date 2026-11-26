import { Fragment, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import {
  admin,
  ago,
  Mission,
  MissionMessage,
  MissionTask,
  money,
  Project,
  Provider,
  streamAdminEvents,
  TaskDiff,
} from "../api";
import type { Tab } from "../App";
import { Empty, ErrorNote, Pill } from "../components/ui";

const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "info" | undefined> = {
  completed: "ok",
  running: "warn",
  planning: "info",
  awaiting_approval: "warn",
  needs_input: "bad",
  failed: "bad",
  cancelled: undefined,
  pending: undefined,
  queued: "info",
};

interface ProjectFormState {
  name: string;
  repo_path: string;
  base_branch: string;
  captain_provider: string;
  approval_mode: "manual" | "auto";
  instructions: string;
  webhook_url: string;
  agent_roles_text: string;
}

const EMPTY_FORM: ProjectFormState = {
  name: "",
  repo_path: "",
  base_branch: "",
  captain_provider: "",
  approval_mode: "manual",
  instructions: "",
  webhook_url: "",
  agent_roles_text: "",
};

function rolesToText(roles: Record<string, string>): string {
  return Object.entries(roles || {})
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
}

function textToRoles(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const idx = line.indexOf(":");
    if (idx <= 0) continue;
    const k = line.slice(0, idx).trim();
    const v = line.slice(idx + 1).trim();
    if (k && v) out[k] = v;
  }
  return out;
}

function friendlyError(raw: string): string {
  const s = raw.trim();
  if (!s) return "";
  if (s.startsWith("bad_workdir:")) {
    return `Worktree folder could not be found. Click Retry to recreate it cleanly. (${s})`;
  }
  if (s.startsWith("no_providers:") || s.includes("No enabled providers")) {
    return "No coding CLI providers are enabled. Open Providers in the sidebar to enable at least one agent.";
  }
  if (s.startsWith("budget_exceeded:")) {
    return `This project reached its budget cap. Raise the limit in Project settings or start a new mission. (${s})`;
  }
  if (s.startsWith("rate_limited:") || s.toLowerCase().includes("rate limit")) {
    return `This agent hit a subscription or API rate limit. Reassign the task or retry later. (${s})`;
  }
  return s;
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**") && tok.endsWith("**")) {
      nodes.push(<strong key={key++}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("`") && tok.endsWith("`")) {
      nodes.push(<code key={key++}>{tok.slice(1, -1)}</code>);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function MarkdownContent({ text }: { text: string }) {
  const segments = text.split(/```(?:[a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g);
  return (
    <div className="captain-msg-body">
      {segments.map((seg, idx) => {
        if (idx % 2 === 1) {
          return <pre key={idx}>{seg.replace(/\n$/, "")}</pre>;
        }
        const lines = seg.split("\n");
        const blocks: ReactNode[] = [];
        let listItems: { ordered: boolean; items: string[] } | null = null;
        const flushList = (k: string) => {
          if (!listItems) return;
          const Tag = listItems.ordered ? "ol" : "ul";
          blocks.push(
            <Tag key={k}>
              {listItems.items.map((item, i) => (
                <li key={i}>{renderInline(item)}</li>
              ))}
            </Tag>,
          );
          listItems = null;
        };
        lines.forEach((line, i) => {
          const trimmed = line.trim();
          if (!trimmed) {
            flushList(`l-${idx}-${i}`);
            return;
          }
          const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
          const olMatch = trimmed.match(/^\d+\.\s+(.+)$/);
          if (ulMatch) {
            if (listItems && listItems.ordered) flushList(`l-${idx}-${i}`);
            if (!listItems) listItems = { ordered: false, items: [] };
            listItems.items.push(ulMatch[1]);
          } else if (olMatch) {
            if (listItems && !listItems.ordered) flushList(`l-${idx}-${i}`);
            if (!listItems) listItems = { ordered: true, items: [] };
            listItems.items.push(olMatch[1]);
          } else {
            flushList(`l-${idx}-${i}`);
            blocks.push(<p key={`p-${idx}-${i}`}>{renderInline(trimmed)}</p>);
          }
        });
        flushList(`l-${idx}-end`);
        return <Fragment key={idx}>{blocks}</Fragment>;
      })}
    </div>
  );
}

export default function Captain({ go }: { go: (t: Tab) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null);
  const [activeMission, setActiveMission] = useState<Mission | null>(null);
  const [liveOutput, setLiveOutput] = useState<Record<number, string>>({});
  const [expandedPrompts, setExpandedPrompts] = useState<Record<number, boolean>>({});
  const [copiedKey, setCopiedKey] = useState<string>("");
  const [orderText, setOrderText] = useState("");
  const [replyText, setReplyText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [modalError, setModalError] = useState("");
  const [notice, setNotice] = useState("");

  const [showProjectModal, setShowProjectModal] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [form, setForm] = useState<ProjectFormState>(EMPTY_FORM);
  const [diffModal, setDiffModal] = useState<{ task: MissionTask; data: TaskDiff } | null>(null);
  const [notifPermission, setNotifPermission] = useState(() => (typeof Notification === "undefined" ? "unsupported" : Notification.permission));
  const streamAbort = useRef<AbortController | null>(null);

  const enabledProviders = providers.filter((p) => p.enabled);
  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null;

  const copyText = (key: string, value: string) => {
    void navigator.clipboard?.writeText(value);
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey((cur) => (cur === key ? "" : cur)), 1800);
  };

  useEffect(() => {
    if (!showProjectModal && !diffModal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setShowProjectModal(false);
        setDiffModal(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showProjectModal, diffModal]);

  const loadBase = useCallback(async () => {
    try {
      const [projs, provs] = await Promise.all([
        admin<Project[]>("GET", "/projects"),
        admin<Provider[]>("GET", "/providers"),
      ]);
      setProjects(projs);
      setProviders(provs);
      setSelectedProjectId((prev) => {
        if (prev && projs.some((p) => p.id === prev)) return prev;
        return projs[0]?.id ?? null;
      });
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBase();
  }, [loadBase]);

  const loadMissions = useCallback(async (projectId: number) => {
    try {
      const list = await admin<Mission[]>("GET", `/projects/${projectId}/missions`);
      setMissions(list);
      setSelectedMissionId((prev) => {
        if (prev && list.some((m) => m.id === prev)) return prev;
        return list[0]?.id ?? null;
      });
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (selectedProjectId === null) {
      setMissions([]);
      setSelectedMissionId(null);
      setActiveMission(null);
      return;
    }
    void loadMissions(selectedProjectId);
  }, [selectedProjectId, loadMissions]);

  const loadMissionDetail = useCallback(async (missionId: string) => {
    try {
      const detail = await admin<Mission>("GET", `/missions/${missionId}`);
      setActiveMission(detail);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    streamAbort.current?.abort();
    setLiveOutput({});
    if (!selectedMissionId) {
      setActiveMission(null);
      return;
    }
    void loadMissionDetail(selectedMissionId);

    const ac = new AbortController();
    streamAbort.current = ac;
    const run = async () => {
      try {
        await streamAdminEvents(
          `/missions/${selectedMissionId}/stream`,
          (ev) => {
            if (ev.event === "mission.updated") {
              const updated = ev.data as unknown as Mission;
              setActiveMission((prev) => (prev ? { ...prev, ...updated, messages: prev.messages } : updated));
              setMissions((prev) => prev.map((m) => (m.id === updated.id ? { ...m, ...updated } : m)));
            } else if (ev.event === "task.updated") {
              const task = ev.data as unknown as MissionTask;
              setActiveMission((prev) => {
                if (!prev) return prev;
                const existing = prev.tasks ?? [];
                const found = existing.some((t) => t.id === task.id);
                return {
                  ...prev,
                  tasks: found ? existing.map((t) => (t.id === task.id ? task : t)) : [...existing, task],
                };
              });
            } else if (ev.event === "task.delta") {
              const d = ev.data as { task_id: number; delta: string };
              setLiveOutput((prev) => ({ ...prev, [d.task_id]: (prev[d.task_id] || "") + d.delta }));
            } else if (ev.event === "message.created") {
              const msg = ev.data as unknown as MissionMessage;
              setActiveMission((prev) => {
                if (!prev) return prev;
                const msgs = prev.messages ?? [];
                if (msgs.some((m) => m.id === msg.id)) return prev;
                return { ...prev, messages: [...msgs, msg] };
              });
            }
          },
          ac.signal,
        );
      } catch {
        /* aborted or closed */
      }
    };
    void run();
    return () => ac.abort();
  }, [selectedMissionId, loadMissionDetail]);

  const openNewProject = () => {
    setEditingProject(null);
    setModalError("");
    setForm({ ...EMPTY_FORM, captain_provider: enabledProviders[0]?.name ?? "" });
    setShowProjectModal(true);
  };

  const openEditProject = (p: Project) => {
    setEditingProject(p);
    setModalError("");
    setForm({
      name: p.name,
      repo_path: p.repo_path,
      base_branch: p.base_branch,
      captain_provider: p.captain_provider,
      approval_mode: p.approval_mode,
      instructions: p.instructions,
      webhook_url: p.webhook_url,
      agent_roles_text: rolesToText(p.agent_roles),
    });
    setShowProjectModal(true);
  };

  const saveProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setModalError("");
    try {
      const payload = {
        name: form.name.trim(),
        repo_path: form.repo_path.trim(),
        base_branch: form.base_branch.trim() || undefined,
        captain_provider: form.captain_provider,
        approval_mode: form.approval_mode,
        instructions: form.instructions,
        webhook_url: form.webhook_url.trim(),
        agent_roles: textToRoles(form.agent_roles_text),
      };
      const saved = editingProject
        ? await admin<Project>("PATCH", `/projects/${editingProject.id}`, payload)
        : await admin<Project>("POST", "/projects", payload);
      setShowProjectModal(false);
      await loadBase();
      setSelectedProjectId(saved.id);
      setNotice(editingProject ? `Updated project "${saved.name}".` : `Created project "${saved.name}".`);
    } catch (err) {
      setModalError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const deleteProject = async (p: Project) => {
    if (
      !confirm(
        `Delete project "${p.name}" and its mission history? Temporary worktrees will be removed; your local repository and git branches are not touched.`,
      )
    ) {
      return;
    }
    try {
      await admin("DELETE", `/projects/${p.id}?cleanup_worktrees=true`);
      setShowProjectModal(false);
      await loadBase();
    } catch (err) {
      setModalError((err as Error).message);
    }
  };

  const testWebhook = async () => {
    if (!editingProject) return;
    setBusy(true);
    setModalError("");
    try {
      await admin("POST", `/projects/${editingProject.id}/test-webhook`, { webhook_url: form.webhook_url.trim() });
      setNotice("Test webhook notification delivered.");
    } catch (err) {
      setModalError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitOrder = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!selectedProject || !orderText.trim() || busy || enabledProviders.length === 0) return;
    setBusy(true);
    setError("");
    try {
      const created = await admin<Mission>("POST", `/projects/${selectedProject.id}/missions`, {
        goal: orderText.trim(),
        channel: "dashboard",
      });
      setOrderText("");
      setMissions((prev) => [created, ...prev]);
      setSelectedMissionId(created.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const approveMission = async () => {
    if (!activeMission) return;
    setBusy(true);
    setError("");
    try {
      const updated = await admin<Mission>("POST", `/missions/${activeMission.id}/approve`, {});
      setActiveMission((prev) => (prev ? { ...prev, ...updated } : updated));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const retryFailedTasks = async () => {
    if (!activeMission) return;
    setBusy(true);
    setError("");
    try {
      const updated = await admin<Mission>("POST", `/missions/${activeMission.id}/retry-failed`, { instruction: "" });
      setActiveMission((prev) => (prev ? { ...prev, ...updated } : updated));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancelMission = async () => {
    if (!activeMission) return;
    setBusy(true);
    try {
      const updated = await admin<Mission>("POST", `/missions/${activeMission.id}/cancel`, {});
      setActiveMission((prev) => (prev ? { ...prev, ...updated } : updated));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const reassignTask = async (task: MissionTask, providerName: string) => {
    try {
      const updated = await admin<MissionTask>("PATCH", `/tasks/${task.id}`, { provider_name: providerName });
      setActiveMission((prev) =>
        prev ? { ...prev, tasks: (prev.tasks ?? []).map((t) => (t.id === updated.id ? updated : t)) } : prev,
      );
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const retryTask = async (task: MissionTask) => {
    try {
      await admin("POST", `/tasks/${task.id}/retry`, { instruction: "" });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const openDiff = async (task: MissionTask) => {
    try {
      const data = await admin<TaskDiff>("GET", `/tasks/${task.id}/diff`);
      setDiffModal({ task, data });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const cleanupWorktree = async (task: MissionTask) => {
    try {
      await admin("POST", `/tasks/${task.id}/cleanup`, { delete_branch: false });
      setActiveMission((prev) =>
        prev
          ? { ...prev, tasks: (prev.tasks ?? []).map((t) => (t.id === task.id ? { ...t, worktree_path: "" } : t)) }
          : prev,
      );
      setNotice(`Removed temporary worktree folder for "${task.title}". Git branch ${task.branch_name} is kept.`);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const sendReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeMission || !replyText.trim()) return;
    setBusy(true);
    setError("");
    try {
      await admin("POST", `/missions/${activeMission.id}/messages`, {
        content: replyText.trim(),
        channel: "dashboard",
      });
      setReplyText("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const hasFailedTasks = Boolean(activeMission?.tasks?.some((t) => t.status === "failed"));
  const hasAdvancedConfig = Boolean(form.agent_roles_text.trim() || form.instructions.trim() || form.webhook_url.trim());

  const replyPlaceholder = (() => {
    if (!activeMission) return "";
    if (activeMission.status === "needs_input") return "Reply to unblock the waiting agent…";
    if (hasFailedTasks) return "Tell Captain how to retry failed tasks (e.g. 'try again')…";
    if (activeMission.status === "awaiting_approval") return "Ask Captain to revise the plan (e.g. 'use claude for task 2')…";
    if (activeMission.status === "completed") return "Ask Captain a follow-up question about this mission…";
    return "Post a note to this mission…";
  })();

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Captain</h1>
          <p className="muted">
            Give one order for a project. Captain splits the work across your coding agents on separate branches and notifies you when it&apos;s ready.
          </p>
        </div>
        <div className="row">
          {notifPermission === "default" && (
            <button className="ghost" onClick={() => void Notification.requestPermission().then(setNotifPermission)}>
              Enable desktop alerts
            </button>
          )}
          <button className="primary" onClick={openNewProject}>
            + New project
          </button>
        </div>
      </div>

      <ErrorNote message={error} />
      {notice && (
        <div className="note ok" role="status">
          {notice}
          <button className="ghost small" style={{ marginLeft: 12 }} onClick={() => setNotice("")}>
            Dismiss
          </button>
        </div>
      )}

      {!loading && enabledProviders.length === 0 && (
        <div className="note warn">
          No coding CLI providers are enabled yet.{" "}
          <button className="link" onClick={() => go("providers")}>
            Enable providers →
          </button>
        </div>
      )}

      {loading ? (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>
            Loading Captain projects…
          </p>
        </div>
      ) : (
        <div className="captain-layout">
          <aside className="captain-rail card">
            <div className="captain-rail-head">
              <label className="small muted" htmlFor="captain-project-select">
                Project
              </label>
              <div className="row">
                <select
                  id="captain-project-select"
                  value={selectedProjectId ?? ""}
                  onChange={(e) => setSelectedProjectId(e.target.value ? Number(e.target.value) : null)}
                  style={{ flex: 1 }}
                >
                  {projects.length === 0 && <option value="">No projects yet</option>}
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
                {selectedProject && (
                  <button className="ghost small" onClick={() => openEditProject(selectedProject)} title="Project settings">
                    Settings
                  </button>
                )}
              </div>
              {selectedProject && (
                <div className="xsmall muted captain-repo-path" title={selectedProject.repo_path}>
                  {selectedProject.repo_path} ({selectedProject.base_branch})
                </div>
              )}
            </div>

            {selectedProject && (
              <form className="captain-order-form" onSubmit={submitOrder}>
                <textarea
                  rows={3}
                  value={orderText}
                  onChange={(e) => setOrderText(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                      e.preventDefault();
                      void submitOrder();
                    }
                  }}
                  placeholder="Give Captain an order for this project… (⌘/Ctrl+Enter to send)"
                  aria-label="New mission order"
                />
                <button className="primary block" type="submit" disabled={busy || !orderText.trim() || enabledProviders.length === 0}>
                  Send order to Captain
                </button>
              </form>
            )}

            <div className="captain-mission-list">
              <div className="small muted" style={{ marginBottom: 6 }}>
                Missions ({missions.length})
              </div>
              {missions.length === 0 ? (
                <p className="small muted">No missions in this project yet.</p>
              ) : (
                missions.map((m) => (
                  <button
                    key={m.id}
                    className={`captain-mission-item ${selectedMissionId === m.id ? "active" : ""}`}
                    onClick={() => setSelectedMissionId(m.id)}
                  >
                    <div className="captain-mission-title">{m.title || m.goal}</div>
                    <div className="row" style={{ justifyContent: "space-between", marginTop: 4 }}>
                      <Pill tone={STATUS_TONE[m.status]}>{m.status.replace("_", " ")}</Pill>
                      <span className="xsmall muted">{ago(m.created_at)}</span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </aside>

          <section className="captain-main">
            {!selectedProject ? (
              <div className="card">
                <Empty>
                  <strong>Create your first project</strong>
                  <p className="small muted">
                    Register a local git repository so Captain can plan tasks, assign them to Claude, Codex, Gemini, or Antigravity, and run each agent on an isolated branch.
                  </p>
                  <button className="primary" onClick={openNewProject}>
                    + New project
                  </button>
                </Empty>
              </div>
            ) : !activeMission ? (
              <div className="card">
                <Empty>
                  <strong>Ready in {selectedProject.name}</strong>
                  <p className="small muted">
                    Enter an order on the left (or run <code>agentbridge captain &quot;...&quot;</code> in your terminal). Captain will propose a task breakdown using your enabled agents and live subscription quotas.
                  </p>
                </Empty>
              </div>
            ) : (
              <div className="captain-detail">
                <div className="card captain-mission-header">
                  <div>
                    <div className="row">
                      <h2 style={{ margin: 0 }}>{activeMission.title || "Mission"}</h2>
                      <Pill tone={STATUS_TONE[activeMission.status]}>{activeMission.status.replace("_", " ")}</Pill>
                    </div>
                    <p className="small muted" style={{ margin: "6px 0 0" }}>
                      Captain: <code>{activeMission.captain_provider}/{activeMission.captain_model || "default"}</code> · Mission{" "}
                      <code>{activeMission.id}</code>
                    </p>
                  </div>
                  <div className="row">
                    {activeMission.status === "awaiting_approval" && (
                      <button className="primary" disabled={busy} onClick={approveMission}>
                        Approve &amp; Run Tasks
                      </button>
                    )}
                    {hasFailedTasks && activeMission.status !== "running" && (
                      <button className="primary" disabled={busy} onClick={retryFailedTasks}>
                        Retry failed tasks
                      </button>
                    )}
                    {["planning", "awaiting_approval", "running", "needs_input"].includes(activeMission.status) && (
                      <button className="ghost" disabled={busy} onClick={cancelMission}>
                        Cancel
                      </button>
                    )}
                  </div>
                </div>

                {(activeMission.tasks?.length ?? 0) > 0 && (
                  <div className="captain-tasks-grid">
                    {(activeMission.tasks ?? []).map((t) => {
                      const streamed = liveOutput[t.id] || t.output_text;
                      const isLongPrompt = t.status !== "pending" && t.description.length > 220;
                      const isPromptExpanded = Boolean(expandedPrompts[t.id]);
                      const hasChanges = Boolean(t.diff_stat && t.diff_stat.trim());
                      return (
                        <div key={t.id} className="card captain-task-card">
                          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                            <div>
                              <strong>{t.title}</strong>
                              {t.rationale && <div className="xsmall muted">{t.rationale}</div>}
                            </div>
                            <Pill tone={STATUS_TONE[t.status]}>{t.status.replace("_", " ")}</Pill>
                          </div>

                          <p className={`small captain-task-desc ${isLongPrompt && !isPromptExpanded ? "clamped" : ""}`}>
                            {t.description}
                          </p>
                          {isLongPrompt && (
                            <button
                              type="button"
                              className="link xsmall"
                              style={{ alignSelf: "flex-start", marginBottom: 8 }}
                              onClick={() => setExpandedPrompts((prev) => ({ ...prev, [t.id]: !prev[t.id] }))}
                            >
                              {isPromptExpanded ? "Hide full prompt" : "Show full prompt"}
                            </button>
                          )}

                          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                            {t.status === "pending" ? (
                              <label className="row xsmall muted">
                                Agent:
                                <select
                                  aria-label={`Assign agent for ${t.title}`}
                                  value={t.provider_name}
                                  onChange={(e) => void reassignTask(t, e.target.value)}
                                >
                                  {enabledProviders.map((p) => (
                                    <option key={p.name} value={p.name}>
                                      {p.name} ({p.default_model})
                                    </option>
                                  ))}
                                </select>
                              </label>
                            ) : (
                              <span className="xsmall muted row" style={{ gap: 6, flexWrap: "wrap" }}>
                                <span>
                                  Agent: <code>{t.provider_name}/{t.model || "default"}</code>
                                </span>
                                {t.branch_name && (
                                  <>
                                    <span>
                                      · Branch: <code>{t.branch_name}</code>
                                    </span>
                                    <button
                                      type="button"
                                      className="ghost captain-copy-btn"
                                      title="Copy branch name"
                                      onClick={() => copyText(`branch-${t.id}`, t.branch_name)}
                                    >
                                      {copiedKey === `branch-${t.id}` ? "Copied" : "Copy"}
                                    </button>
                                  </>
                                )}
                                {t.cost_usd > 0 && <span>· {money(t.cost_usd)}</span>}
                              </span>
                            )}

                            <div className="row">
                              {t.worktree_path && (hasChanges || t.status === "running") && (
                                <button className="ghost small" onClick={() => void openDiff(t)}>
                                  View diff
                                </button>
                              )}
                              {["failed", "needs_input"].includes(t.status) && (
                                <button className="ghost small" onClick={() => void retryTask(t)}>
                                  Retry
                                </button>
                              )}
                              {t.worktree_path && t.status !== "running" && (
                                <button
                                  className="ghost small"
                                  title="Remove temporary worktree folder (keeps git branch)"
                                  onClick={() => void cleanupWorktree(t)}
                                >
                                  Cleanup worktree
                                </button>
                              )}
                            </div>
                          </div>

                          {t.error && (
                            <div className="note bad small" style={{ marginTop: 8 }}>
                              {friendlyError(t.error)}
                            </div>
                          )}
                          {hasChanges && <pre className="captain-pre xsmall">{t.diff_stat}</pre>}
                          {streamed && (
                            <details open={t.status === "running" || t.status === "needs_input" || t.status === "completed"} style={{ marginTop: 8 }}>
                              <summary className="xsmall muted">Agent output</summary>
                              <pre className="captain-pre xsmall">{streamed.slice(-4000)}</pre>
                            </details>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="card captain-timeline">
                  <h3 style={{ marginTop: 0 }}>Communication channel</h3>
                  <div className="captain-messages">
                    {(activeMission.messages ?? []).map((msg) => (
                      <div key={msg.id} className={`captain-msg sender-${msg.sender_type} kind-${msg.kind}`}>
                        <div className="row xsmall muted" style={{ justifyContent: "space-between" }}>
                          <span>
                            <strong>{msg.sender_name || msg.sender_type}</strong> · {msg.kind} ({msg.channel})
                          </span>
                          <span>{ago(msg.created_at)}</span>
                        </div>
                        <MarkdownContent text={msg.content} />
                      </div>
                    ))}
                  </div>

                  {["needs_input", "running", "awaiting_approval", "completed", "failed"].includes(activeMission.status) && (
                    <form className="row" style={{ marginTop: 12 }} onSubmit={sendReply}>
                      <input
                        type="text"
                        style={{ flex: 1 }}
                        value={replyText}
                        onChange={(e) => setReplyText(e.target.value)}
                        placeholder={replyPlaceholder}
                      />
                      <button className="primary" type="submit" disabled={busy || !replyText.trim()}>
                        Send
                      </button>
                    </form>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {showProjectModal && (
        <div className="modal-backdrop" onClick={() => setShowProjectModal(false)}>
          <form className="card modal-card" onClick={(e) => e.stopPropagation()} onSubmit={saveProject}>
            <h2 style={{ margin: 0 }}>{editingProject ? `Project settings: ${editingProject.name}` : "New Captain project"}</h2>
            <div className="modal-body">
              <ErrorNote message={modalError} />
              <label className="field">
                <span>Project name</span>
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. AgentBridge" />
              </label>
              <label className="field">
                <span>Local git repository path</span>
                <input
                  required
                  disabled={Boolean(editingProject)}
                  value={form.repo_path}
                  onChange={(e) => setForm({ ...form, repo_path: e.target.value })}
                  placeholder="/Users/you/code/my-repo"
                />
              </label>
              <div className="row">
                <label className="field" style={{ flex: 1 }}>
                  <span>Base branch</span>
                  <input value={form.base_branch} onChange={(e) => setForm({ ...form, base_branch: e.target.value })} placeholder="main (auto-detected)" />
                </label>
                <label className="field" style={{ flex: 1 }}>
                  <span>Captain provider</span>
                  <select value={form.captain_provider} onChange={(e) => setForm({ ...form, captain_provider: e.target.value })}>
                    <option value="">First enabled provider</option>
                    {enabledProviders.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label className="field">
                <span>Approval mode</span>
                <select
                  value={form.approval_mode}
                  onChange={(e) => setForm({ ...form, approval_mode: e.target.value as "manual" | "auto" })}
                >
                  <option value="manual">Manual — review &amp; approve plan before spawning agents (recommended)</option>
                  <option value="auto">Auto — dispatch planned tasks immediately</option>
                </select>
              </label>
              <details className="advanced-paths" open={hasAdvancedConfig}>
                <summary className="small">Advanced settings (agent roles, instructions, webhook alerts)</summary>
                <div className="details-body">
                  <label className="field">
                    <span>Agent role hints (one per line: provider: role)</span>
                    <textarea
                      rows={2}
                      value={form.agent_roles_text}
                      onChange={(e) => setForm({ ...form, agent_roles_text: e.target.value })}
                      placeholder={"claude: backend & architecture\ncodex: tests & refactoring"}
                    />
                  </label>
                  <label className="field">
                    <span>Project Captain instructions (optional)</span>
                    <textarea
                      rows={2}
                      value={form.instructions}
                      onChange={(e) => setForm({ ...form, instructions: e.target.value })}
                      placeholder="Any extra guidelines for this project's Captain and worker agents…"
                    />
                  </label>
                  <label className="field">
                    <span>Notification webhook URL (Slack, Discord, ntfy, or JSON)</span>
                    <div className="row">
                      <input
                        style={{ flex: 1 }}
                        value={form.webhook_url}
                        onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
                        placeholder="https://hooks.slack.com/services/… or https://discord.com/api/webhooks/…"
                      />
                      {editingProject && (
                        <button type="button" className="ghost" disabled={busy || !form.webhook_url.trim()} onClick={testWebhook}>
                          Test
                        </button>
                      )}
                    </div>
                  </label>
                </div>
              </details>
            </div>
            <div className="modal-footer">
              <div>
                {editingProject && (
                  <button type="button" className="ghost" onClick={() => void deleteProject(editingProject)}>
                    Delete project
                  </button>
                )}
              </div>
              <div className="row">
                <button type="button" className="ghost" onClick={() => setShowProjectModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="primary" disabled={busy}>
                  {editingProject ? "Save settings" : "Create project"}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {diffModal && (
        <div className="modal-backdrop" onClick={() => setDiffModal(null)}>
          <div className="card modal-card modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 style={{ margin: 0 }}>
                Diff: {diffModal.task.title} (<code>{diffModal.data.branch_name}</code>)
              </h2>
              <button className="ghost" onClick={() => setDiffModal(null)}>
                Close
              </button>
            </div>
            {diffModal.data.diff ? (
              <>
                <div className="captain-merge-box">
                  <div className="small">
                    Changes live on <code>{diffModal.data.branch_name}</code> — your base branch is untouched. Merge locally:
                    <div>
                      <code>git merge {diffModal.data.branch_name}</code>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => copyText(`merge-${diffModal.task.id}`, `git merge ${diffModal.data.branch_name}`)}
                  >
                    {copiedKey === `merge-${diffModal.task.id}` ? "Copied!" : "Copy merge command"}
                  </button>
                </div>
                <pre className="captain-pre captain-diff">{diffModal.data.diff}</pre>
              </>
            ) : (
              <p className="muted">No file changes in this worktree yet.</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
