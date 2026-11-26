import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { admin, InstructionFile, InstructionResult, InstructionStatus, InstructionTarget, SkillFile, SkillIssue, SkillLink, SkillLinkResult, SkillsState, WrapperFile } from "../api";
import { ErrorNote, Field, Modal, Pill } from "../components/ui";

type AnyFile = SkillFile | WrapperFile | InstructionFile;
type Kind = AnyFile["kind"];
type Sel = { kind: Kind; name: string };
type View = "edit" | "preview" | "changes";
type Draft = { text: string; base: string };

const LINK_TEXT: Record<SkillLink, string> = { linked: "linked", missing: "not linked", stale: "points elsewhere", conflict: "blocked by a real file" };
const APPLY_TEXT: Record<InstructionStatus, string> = { applied: "linked", outdated: "out of date", edited: "edited by hand", missing: "not linked" };
const APPLY_PIP: Record<InstructionStatus, SkillLink> = { applied: "linked", outdated: "stale", edited: "conflict", missing: "missing" };
const NAME_PATTERN = "[a-z0-9]+(-[a-z0-9]+)*";
const keyOf = (s: Sel) => `${s.kind}:${s.name}`;
const POLL_MS = 3000;

// Drafts outlive the page so switching dashboard sections doesn't drop unsaved edits.
const draftStore = new Map<string, Draft>();
const issueStore = new Map<string, SkillIssue[]>();

const worst = (list: SkillIssue[]) => (list.some((i) => i.level === "error") ? "bad" : list.some((i) => i.level === "warn") ? "warn" : "ok");
const filesOf = (s: SkillsState, kind: Kind): AnyFile[] => (kind === "skill" ? s.skills : kind === "wrapper" ? s.wrappers : s.instructions.files);
/** The agents an instructions file reaches: every agent for global, one agent otherwise. */
const reachOf = (s: SkillsState, f: InstructionFile): InstructionTarget[] => s.instructions.targets.filter((t) => f.name === "global" || t.id === f.name);
const fullyLinked = (s: SkillsState, f: AnyFile) =>
  f.kind === "skill" ? Object.values(f.linked).every((v) => v === "linked")
    : f.kind === "wrapper" ? f.linked === "linked"
      : reachOf(s, f).every((t) => t.status === "applied");
const titleOf = (f: AnyFile) => (f.kind === "instructions" ? (f.name === "global" ? "Global instructions" : `${f.label} instructions`) : f.name);
/** What one agent receives, matching SkillsRepo.composed on the server. */
const compose = (global: string, own: string) => [global, own].map((t) => t.replace(/^\n+|\n+$/g, "")).filter((t) => t.trim()).join("\n\n");
const instructionText = (s: SkillsState, name: string) => s.instructions.files.find((f) => f.name === name)?.text ?? "";
/** Whether an agent would receive any text: the global instructions plus its own. */
const hasText = (s: SkillsState, t: InstructionTarget) => !!compose(instructionText(s, "global"), instructionText(s, t.id)).trim();
/** Agents that Link would change: out of date or not linked yet, with something to write (matches the server, which never writes an empty block over one that's there). */
const pendingOf = (s: SkillsState, targets: InstructionTarget[]) =>
  targets.filter((t) => (t.status === "outdated" || t.status === "missing") && hasText(s, t));
/** A block written from a different instructions folder, such as another AgentBridge install. */
const fromElsewhere = (s: SkillsState, t: InstructionTarget) => t.status !== "missing" && !!t.source && t.source !== s.instructions.dir;
const targetText = (s: SkillsState, t: InstructionTarget) =>
  t.status === "outdated" && fromElsewhere(s, t) ? "linked from another folder" : APPLY_TEXT[t.status];
/** Unsaved drafts on one page; the Skills and Instructions pages keep theirs apart. */
const unsavedCount = (mode: "skills" | "instructions") =>
  [...draftStore.keys()].filter((k) => k.startsWith("instructions:") === (mode === "instructions")).length;

/** The Skills and Instructions pages share one editor; `mode` picks which files it lists. */
export default function Skills({ mode = "skills" }: { mode?: "skills" | "instructions" }) {
  const listed = useCallback((s: SkillsState): AnyFile[] => (mode === "instructions" ? s.instructions.files : [...s.skills, ...s.wrappers]), [mode]);
  const [state, setState] = useState<SkillsState | null>(null);
  const [error, setError] = useState("");
  const [sel, setSel] = useState<Sel | null>(null);
  const [view, setView] = useState<View>("edit");
  const [, bump] = useState(0);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [linkResult, setLinkResult] = useState<SkillLinkResult[] | null>(null);
  const [linking, setLinking] = useState(false);
  const rerender = () => bump((n) => n + 1);

  const apply = useCallback((next: SkillsState) => {
    for (const [k, d] of draftStore) {
      const [kind, name] = k.split(/:(.*)/);
      const f = filesOf(next, kind as Kind).find((x) => x.name === name);
      if (!f || f.text === d.text) { draftStore.delete(k); issueStore.delete(k); }
    }
    setState(next);
    setSel((cur) => {
      const all = listed(next);
      if (cur && all.some((f) => f.kind === cur.kind && f.name === cur.name)) return cur;
      return all[0] ? { kind: all[0].kind, name: all[0].name } : null;
    });
  }, [listed]);

  const lastSeen = useRef("");
  const load = useCallback(() => admin<SkillsState>("GET", "/skills").then((s) => {
    const seen = JSON.stringify(s);
    if (seen !== lastSeen.current) { lastSeen.current = seen; apply(s); }
    setError("");
  }).catch((e) => setError(e.message)), [apply]);
  useEffect(() => {
    void load();
    // Follow edits that agents or other editors make on disk while the page is visible.
    const poll = window.setInterval(() => { if (document.visibilityState === "visible") void load(); }, POLL_MS);
    const onShow = () => { if (document.visibilityState === "visible") void load(); };
    window.addEventListener("focus", onShow);
    document.addEventListener("visibilitychange", onShow);
    const onUnload = (e: BeforeUnloadEvent) => { if (draftStore.size) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.clearInterval(poll);
      window.removeEventListener("focus", onShow);
      document.removeEventListener("visibilitychange", onShow);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [load]);

  const file: AnyFile | undefined = useMemo(() => {
    if (!state || !sel) return undefined;
    return filesOf(state, sel.kind).find((f) => f.name === sel.name);
  }, [state, sel]);

  const draftOf = (f: AnyFile) => draftStore.get(keyOf(f));
  const textOf = (f: AnyFile) => draftOf(f)?.text ?? f.text;
  const dirty = (f: AnyFile) => !!draftOf(f);
  const issuesOf = (f: AnyFile) => issueStore.get(keyOf(f)) ?? f.issues;

  const validateTimer = useRef<number>();
  const edit = (f: AnyFile, text: string) => {
    const k = keyOf(f);
    if (text === f.text) { draftStore.delete(k); issueStore.delete(k); }
    else draftStore.set(k, { text, base: draftOf(f)?.base ?? f.text });
    setNotice("");
    rerender();
    window.clearTimeout(validateTimer.current);
    validateTimer.current = window.setTimeout(async () => {
      try {
        const r = await admin<{ issues: SkillIssue[] }>("POST", `/skills/${f.kind}/${f.name}/validate`, { text });
        if (draftStore.get(k)?.text === text) { issueStore.set(k, r.issues); rerender(); }
      } catch { /* checks refresh on save */ }
    }, 300);
  };

  const savingRef = useRef(false);
  const save = useCallback(async () => {
    if (!file || savingRef.current) return;  // ⌘S pressed again while a save is in flight
    const d = draftStore.get(keyOf(file));
    if (!d) return;
    savingRef.current = true;
    setSaving(true);
    setError("");
    try {
      const next = await admin<SkillsState>("PUT", `/skills/${file.kind}/${file.name}`, { text: d.text, base: d.base });
      apply(next);
      if (file.kind === "instructions") {
        const reach = reachOf(next, file);
        const done = reach.filter((t) => t.status === "applied").map((t) => t.label);
        const waiting = reach.filter((t) => t.status !== "applied").map((t) => t.label);
        setNotice(`Saved ${titleOf(file).toLowerCase()}.${done.length ? ` ${listOf(done)} ${done.length === 1 ? "has" : "have"} the update.` : ""}${waiting.length ? ` Link to add it to ${listOf(waiting)}.` : ""}`);
      } else setNotice(`Saved ${file.name}. Every agent links to this file, so they all see the change now.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [file, apply]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") { e.preventDefault(); void save(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [save]);

  const link = async () => {
    setLinking(true);
    setError("");
    try {
      const r = await admin<{ links: SkillLinkResult[]; state: SkillsState }>("POST", "/skills/link");
      apply(r.state);
      setLinkResult(r.links);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLinking(false);
    }
  };

  /** Link or unlink one skill (in the given agents, or all) or one wrapper. */
  const linkOne = async (f: SkillFile | WrapperFile, action: "link" | "unlink", targets?: { id: string; label: string }[]) => {
    setLinking(true);
    setError("");
    try {
      const r = await admin<{ links: SkillLinkResult[]; state: SkillsState }>("POST", `/skills/${f.kind}/${f.name}/${action}`, { targets: targets?.map((t) => t.id) ?? null });
      apply(r.state);
      setNotice(linkSummary(f, action, r.links, r.state));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLinking(false);
    }
  };

  const applyInstructions = async (targets: string[], force = false) => {
    setLinking(true);
    setError("");
    try {
      const r = await admin<{ results: InstructionResult[]; state: SkillsState }>("POST", "/skills/instructions/apply", { targets, force });
      apply(r.state);
      setNotice(instructionSummary(r.results, r.state));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLinking(false);
    }
  };

  const removeInstructions = async (target: InstructionTarget) => {
    setLinking(true);
    setError("");
    try {
      const r = await admin<{ results: InstructionResult[]; state: SkillsState }>("POST", "/skills/instructions/remove", { target: target.id });
      apply(r.state);
      setNotice(`Unlinked the instructions from ${target.label}. Only the AgentBridge block in ${target.path} was removed; the rest of the file is unchanged.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLinking(false);
    }
  };

  const unsaved = unsavedCount(mode);
  const pendingAll = state ? pendingOf(state, state.instructions.targets) : [];
  const head = (
    <div className="page-head">
      <div>
        <h1>{mode === "instructions" ? "Instructions" : "Skills"}</h1>
        <p className="muted">
          {mode === "instructions" ? "Global instructions for Claude Code, Codex and Antigravity" : "Shared skills for Claude Code, Codex and Antigravity"}
          {state ? (mode === "instructions"
            ? <> from <Folder s={state} path={state.instructions.dir} /></>
            : <> from <Folder s={state} path={state.skills_dir} />, with Claude Code wrappers in <Folder s={state} path={state.wrappers_dir} /></>) : null}.{" "}
          {mode === "instructions"
            ? "Write what every agent should follow once, then add anything specific to one agent. AgentBridge writes the result into each agent's global instructions file."
            : "Each agent links to the same source file, so a saved edit reaches all of them at once."}
        </p>
      </div>
      {mode === "skills" ? (
        <div className="row">
          <button onClick={() => setCreating(true)} disabled={!state?.exists}>New skill</button>
          <button onClick={() => void link()} disabled={linking || !state?.exists}>{linking ? "Linking…" : "Link to agents"}</button>
        </div>
      ) : pendingAll.length > 0 && (
        <button disabled={linking || unsaved > 0}
          title={unsaved ? "Save your edits first; Link writes the saved files." : undefined}
          onClick={() => void applyInstructions(pendingAll.map((t) => t.id))}>
          {linking ? "Linking…" : "Link to agents"}
        </button>
      )}
    </div>
  );

  if (!state) return <>{head}<ErrorNote message={error} />{!error && <p>Loading skills…</p>}</>;

  const all = listed(state);
  const errorCount = all.filter((f) => worst(issuesOf(f)) === "bad").length;
  const unlinked = all.filter((f) => !fullyLinked(state, f)).length;
  const appliedCount = state.instructions.targets.filter((t) => t.status === "applied").length;
  const globalFile = state.instructions.files.find((f) => f.name === "global")!;

  return (
    <>
      {head}
      {!state.exists && <p className="note bad">AgentBridge couldn't create the skills folder at {state.root}. Check that your home folder is writable, then reload.</p>}
      <ErrorNote message={error} />
      {notice && <p className="note ok" role="status">{notice}</p>}
      {state.exists && (
        <div className="row skills-summary">
          {mode === "skills" ? <>
            <Pill tone="info">{plural(state.skills.length, "skill")} · {plural(state.wrappers.length, "wrapper")}</Pill>
            {all.length > 0 && <>
              <Pill tone={errorCount ? "bad" : "ok"}>{errorCount ? `${errorCount} with errors` : "All checks pass"}</Pill>
              <Pill tone={unlinked ? "warn" : "ok"}>{unlinked ? `${unlinked} not linked everywhere` : "Linked in every agent"}</Pill>
            </>}
          </> : <>
            <Pill tone={appliedCount === state.instructions.targets.length ? "ok" : "warn"}>Up to date in {appliedCount} of {state.instructions.targets.length} agents</Pill>
            {errorCount > 0 && <Pill tone="bad">{errorCount} with errors</Pill>}
          </>}
          {unsaved > 0 && <Pill tone="warn">{unsaved} unsaved</Pill>}
        </div>
      )}

      {state.exists && (
        <div className="skills-layout">
          <nav className="card skills-list" aria-label={mode === "instructions" ? "Instruction files" : "Skill files"}>
            {mode === "instructions" ? <>
            <div className="skills-group-label">Shared</div>
            {state.instructions.files.slice(0, 1).map((f) => (
              <ListItem key={keyOf(f)} f={f} sel={sel} onSelect={setSel} tone={worst(issuesOf(f))} dirty={dirty(f)} title="All agents" sub="global.md · every agent gets it"
                pips={reachOf(state, f).map((t) => ({ label: t.label, status: APPLY_PIP[t.status], text: targetText(state, t) }))} />
            ))}
            <div className="skills-group-label">Per agent</div>
            {state.instructions.files.slice(1).map((f) => (
              <ListItem key={keyOf(f)} f={f} sel={sel} onSelect={setSel} tone={worst(issuesOf(f))} dirty={dirty(f)}
                title={f.label}
                sub={f.text.trim() ? `${f.name}.md · added after global` : `${f.name}.md · global only`}
                pips={reachOf(state, f).map((t) => ({ label: t.label, status: APPLY_PIP[t.status], text: targetText(state, t) }))} />
            ))}
            </> : <>
            <div className="skills-group-label">Skills</div>
            {state.skills.length ? state.skills.map((f) => (
              <ListItem key={keyOf(f)} f={f} sel={sel} onSelect={setSel} tone={worst(issuesOf(f))} dirty={dirty(f)}
                sub={f.wrappers.length ? `via ${f.wrappers.join(", ")}` : "no wrapper"}
                pips={state.targets.map((t) => ({ label: t.label, status: f.linked[t.id] }))} />
            )) : <p className="muted small">No skills yet.</p>}
            <div className="skills-group-label">Claude Code wrappers</div>
            {state.wrappers.length ? state.wrappers.map((f) => (
              <ListItem key={keyOf(f)} f={f} sel={sel} onSelect={setSel} tone={worst(issuesOf(f))} dirty={dirty(f)}
                sub={f.skill ? `runs ${f.skill}` : "no skill"} pips={[{ label: "~/.claude/agents", status: f.linked }]} />
            )) : <p className="muted small">No wrappers yet.</p>}
            </>}
          </nav>

          {file ? (
            <section className="card skills-editor" aria-label={`Editing ${file.name}`}>
              <div className="card-head">
                <div className="grow">
                  <div className="row">
                    <h2>{titleOf(file)}</h2>
                    <Pill>{file.kind === "skill" ? "Skill" : file.kind === "wrapper" ? "Wrapper" : "Instructions"}</Pill>
                    {dirty(file) && <Pill tone="warn">Unsaved</Pill>}
                  </div>
                  <div className="mono small muted clip" title={file.path}>{file.path}</div>
                </div>
                <div className="row">
                  <button className="ghost" disabled={!dirty(file) || saving} onClick={() => { draftStore.delete(keyOf(file)); issueStore.delete(keyOf(file)); setNotice(""); rerender(); }}>Revert</button>
                  <button className="primary" disabled={!dirty(file) || saving} onClick={() => void save()} title="Save (⌘S / Ctrl+S)">{saving ? "Saving…" : "Save"}</button>
                </div>
              </div>

              {draftOf(file) && draftOf(file)!.base !== file.text && (
                <p className="note warn" role="status">
                  {titleOf(file)} changed on disk while you were editing. Saving is blocked so that change isn't overwritten. Copy your edits if you need them, then Revert to load the new version.
                </p>
              )}

              {file.kind === "instructions"
                ? <InstructionChecks file={file} state={state} issues={issuesOf(file)} busy={linking} unsaved={dirty(file) || (file.name !== "global" && dirty(globalFile))}
                    onApply={(ids, force) => void applyInstructions(ids, force)} onRemove={(t) => void removeInstructions(t)} />
                : <Checks file={file} state={state} issues={issuesOf(file)} busy={linking} onGo={setSel}
                    onLink={(targets) => void linkOne(file, "link", targets)} onUnlink={(targets) => void linkOne(file, "unlink", targets)} />}

              <div className="row spread skills-tabs">
                <div className="seg" role="tablist" aria-label="View">
                  {(["edit", "preview", "changes"] as View[]).map((v) => (
                    <button key={v} role="tab" aria-selected={view === v} className={view === v ? "active" : ""} onClick={() => setView(v)}>
                      {v === "edit" ? "Edit" : v === "preview" ? "Preview" : `Changes${dirty(file) ? ` (${diffCount(file.text, textOf(file))})` : ""}`}
                    </button>
                  ))}
                </div>
                <span className="muted small">⌘S / Ctrl+S saves</span>
              </div>

              {view === "edit" && (
                <textarea className="mono skills-code" value={textOf(file)} spellCheck={false} aria-label={`Contents of ${file.kind === "instructions" ? titleOf(file).toLowerCase() : file.name}`}
                  placeholder={file.kind === "instructions" ? (file.name === "global" ? "Instructions every agent follows, for example coding style, how to run tests, or how to write commit messages." : `Extra instructions only ${(file as InstructionFile).label} gets. They come after the global instructions.`) : undefined}
                  onChange={(e) => edit(file, e.target.value)} />
              )}
              {view === "preview" && (file.kind === "instructions"
                ? <Preview plain text={file.name === "global" ? textOf(file) : compose(textOf(globalFile), textOf(file))}
                    intro={file.name === "global" ? "Every agent gets these, followed by its own instructions." : `What ${file.label} gets: the global instructions, then these.`} />
                : <Preview text={textOf(file)} />)}
              {view === "changes" && (dirty(file) ? <Diff a={file.text} b={textOf(file)} /> : <p className="empty">No unsaved changes. Edits show up here as a diff against the file on disk.</p>)}
            </section>
          ) : (
            <section className="card"><p className="empty">Add a skill to get started.</p></section>
          )}
        </div>
      )}

      {creating && <NewSkill onClose={() => setCreating(false)} onCreated={(r, name) => {
        apply(r.state);
        setSel({ kind: "skill", name });
        setView("edit");
        setCreating(false);
        if (r.links) setLinkResult(r.links);
        else setNotice(`Created ${name}. Link it into the agents when you're ready.`);
      }} />}
      {linkResult && <LinkResults results={linkResult} onClose={() => setLinkResult(null)} />}
    </>
  );
}

function ListItem({ f, sel, onSelect, tone, dirty, sub, pips, title }: {
  f: AnyFile; sel: Sel | null; onSelect: (s: Sel) => void; tone: string; dirty: boolean; sub: string; pips: { label: string; status: SkillLink; text?: string }[]; title?: string;
}) {
  const current = sel?.kind === f.kind && sel.name === f.name;
  return (
    <button className={`skills-item${current ? " active" : ""}`} aria-current={current ? "true" : undefined} onClick={() => onSelect({ kind: f.kind, name: f.name })}>
      <span className={`skills-dot ${tone}`} aria-label={tone === "bad" ? "Has errors" : tone === "warn" ? "Has warnings" : "Checks pass"} />
      <span className="grow">
        <span className="skills-name clip">{title ?? f.name}{dirty && <span className="skills-dirty" title="Unsaved changes"> ●</span>}</span>
        <span className="skills-sub clip">{sub}</span>
      </span>
      <span className="skills-pips" aria-label={pips.map((p) => `${p.label}: ${p.text ?? LINK_TEXT[p.status]}`).join(", ")}>
        {pips.map((p) => <span key={p.label} className={`skills-pip ${p.status}`} title={`${p.label}: ${p.text ?? LINK_TEXT[p.status]}`} />)}
      </span>
    </button>
  );
}

type LinkRow = { id: string; label: string; path: string; status: SkillLink };

/** One row per place the file is linked: each agent's skills folder for a skill, ~/.claude/agents for a wrapper. */
const linkRows = (state: SkillsState, file: SkillFile | WrapperFile): LinkRow[] =>
  file.kind === "skill"
    ? state.targets.map((t) => ({ id: t.id, label: t.label, path: `${t.dir}/${file.name}`, status: file.linked[t.id] }))
    : [{ id: "claude", label: "Claude Code", path: `${state.agents_dir}/${file.name}.md`, status: file.linked }];

function Checks({ file, state, issues, busy, onGo, onLink, onUnlink }: {
  file: SkillFile | WrapperFile; state: SkillsState; issues: SkillIssue[]; busy: boolean; onGo: (s: Sel) => void;
  onLink: (targets: LinkRow[]) => void; onUnlink: (targets: LinkRow[]) => void;
}) {
  const rows = linkRows(state, file);
  const toLink = rows.filter((t) => t.status === "missing" || t.status === "stale");
  const linked = rows.filter((t) => t.status === "linked");
  const blocked = rows.filter((t) => t.status === "conflict");
  return (
    <div className="skills-checks">
      <div className="row spread">
        <span className="muted small grow">
          {file.kind === "skill"
            ? "Each agent gets a link to this skill's folder, so it reads the same file. Unlinking removes only the link; the skill stays here."
            : "Claude Code gets a link to this wrapper in its agents folder. Unlinking removes only the link."}
        </span>
        <div className="row">
          {toLink.length > 1 && (
            <button className="small" disabled={busy} onClick={() => onLink(toLink)}>
              {busy ? "Working…" : toLink.length === rows.length ? "Link to all agents" : `Link to ${listOf(toLink.map((t) => t.label))}`}
            </button>
          )}
          {linked.length > 1 && (
            <button className="small ghost" disabled={busy} onClick={() => onUnlink(linked)}>Unlink from all</button>
          )}
        </div>
      </div>
      <ul className="plain skills-targets">
        {rows.map((t) => (
          <li key={t.id}>
            <Pill tone={t.status === "linked" ? "ok" : t.status === "conflict" ? "bad" : "warn"}>{t.label}: {LINK_TEXT[t.status]}</Pill>
            <span className="mono small skills-target-path" title={t.path}>{t.path}</span>
            {t.status === "linked"
              ? <button className="small ghost" disabled={busy} aria-label={`Unlink from ${t.label}`} onClick={() => onUnlink([t])}>Unlink</button>
              : t.status !== "conflict" && <button className="small" disabled={busy} aria-label={`Link to ${t.label}`} onClick={() => onLink([t])}>{t.status === "stale" ? "Relink" : "Link"}</button>}
          </li>
        ))}
      </ul>
      {blocked.length > 0 && (
        <p className="note warn">
          A real file or folder is already at {listOf(blocked.map((t) => t.path))}, so AgentBridge won't link or unlink there. Move it aside, then link again.
        </p>
      )}
      <div className="row">
        {file.kind === "skill" ? (
          <>
            <span className="muted small skills-label">Wrapper</span>
            {file.wrappers.length ? file.wrappers.map((w) => <button key={w} className="link" onClick={() => onGo({ kind: "wrapper", name: w })}>{w}</button>) : <span className="small">none</span>}
            {file.files.length > 0 && <span className="muted small">· also contains {file.files.map((x) => <code key={x}>{x}</code>)}</span>}
          </>
        ) : (
          <>
            <span className="muted small skills-label">Runs skill</span>
            {file.skill && state.skills.some((s) => s.name === file.skill)
              ? <button className="link" onClick={() => onGo({ kind: "skill", name: file.skill! })}>{file.skill}</button>
              : <span className="small">{file.skill ?? "none"}</span>}
          </>
        )}
      </div>
      <IssueList issues={issues} />
    </div>
  );
}

function IssueList({ issues }: { issues: SkillIssue[] }) {
  return issues.length ? (
        <ul className="plain skills-issues">
          {issues.map((i, n) => (
            <li key={n} className="row nowrap">
              <span className={`skills-level ${i.level}`}>{i.level === "warn" ? "Warning" : i.level === "error" ? "Error" : "Note"}</span>
              <span>{inline(i.message)}</span>
            </li>
          ))}
        </ul>
      ) : <p className="ok-text small">✓ All checks pass</p>;
}

/** A folder path with the home folder shown as ~; hovering shows the full path. */
function Folder({ s, path }: { s: SkillsState; path: string }) {
  const home = s.user_home?.replace(/\/+$/, "");
  const short = home && (path === home || path.startsWith(`${home}/`)) ? `~${path.slice(home.length)}` : path;
  return <code title={path}>{short}</code>;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const listOf = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

function linkSummary(f: SkillFile | WrapperFile, action: "link" | "unlink", results: SkillLinkResult[], state: SkillsState): string {
  const label = (path: string) => (f.kind === "wrapper" ? "Claude Code" : state.targets.find((t) => path === `${t.dir}/${f.name}`)?.label ?? path);
  const done = results.filter((r) => (action === "link" ? r.status === "linked" || r.status === "relinked" : r.status === "removed")).map((r) => label(r.path));
  const skipped = results.filter((r) => r.status === "skipped").map((r) => label(r.path));
  return [
    done.length ? `${action === "link" ? "Linked" : "Unlinked"} ${f.name} ${action === "link" ? "to" : "from"} ${listOf(done)}.`
      : skipped.length ? "" : `${f.name} was already ${action === "link" ? "linked" : "unlinked"} there.`,
    skipped.length ? `Left ${listOf(skipped)} alone: ${results.find((r) => r.status === "skipped")?.detail ?? "something else is there."}` : "",
  ].filter(Boolean).join(" ");
}

function instructionSummary(results: InstructionResult[], state: SkillsState): string {
  const label = (path: string) => state.instructions.targets.find((t) => t.path === path)?.label ?? path;
  const written = results.filter((r) => r.status === "added" || r.status === "updated").map((r) => label(r.path));
  const skipped = results.filter((r) => r.status === "skipped").map((r) => label(r.path));
  return [
    written.length ? `Linked the instructions to ${listOf(written)}.` : skipped.length ? "" : "Everything was already up to date.",
    skipped.length ? `Skipped ${listOf(skipped)}: the AgentBridge block there was edited by hand. Click "overwrite the block" below to replace it.` : "",
  ].filter(Boolean).join(" ");
}

function InstructionChecks({ file, state, issues, busy, unsaved, onApply, onRemove }: {
  file: InstructionFile; state: SkillsState; issues: SkillIssue[]; busy: boolean; unsaved: boolean;
  onApply: (ids: string[], force?: boolean) => void; onRemove: (t: InstructionTarget) => void;
}) {
  const reach = reachOf(state, file);
  const pending = pendingOf(state, reach);
  const edited = reach.filter((t) => t.status === "edited");
  const foreign = reach.filter((t) => fromElsewhere(state, t));
  const kept = reach.filter((t) => t.status !== "missing" && !hasText(state, t));
  const why = unsaved ? "Save your edits first; Link writes the saved files." : undefined;
  return (
    <div className="skills-checks">
      <div className="row spread">
        <span className="muted small grow">
          {file.name === "global" ? "Written into every agent's global instructions file, followed by that agent's own instructions." : `Added after the global instructions in ${file.label}'s global instructions file.`}
          {" "}Text outside the AgentBridge block is yours and stays as it is.
        </span>
        {pending.length > 0 && (
          <button className="small" disabled={busy || !!why} title={why} onClick={() => onApply(pending.map((t) => t.id))}>
            {busy ? "Linking…" : pending.length === reach.length && reach.length > 1 ? "Link to all agents" : `Link to ${listOf(pending.map((t) => t.label))}`}
          </button>
        )}
      </div>
      <ul className="plain skills-targets">
        {reach.map((t) => (
          <li key={t.id}>
            <Pill tone={t.status === "applied" ? "ok" : t.status === "edited" ? "bad" : "warn"}>{t.label}: {targetText(state, t)}</Pill>
            <span className="mono small skills-target-path" title={t.path}>{t.path}{t.own_lines > 0 && <span className="muted"> · plus {t.own_lines} {t.own_lines === 1 ? "line" : "lines"} of your own</span>}</span>
            {t.status !== "missing" && <button className="small ghost" disabled={busy} aria-label={`Unlink from ${t.label}`} onClick={() => onRemove(t)}>Unlink</button>}
          </li>
        ))}
      </ul>
      {(foreign.length > 0 || kept.length > 0) && (
        <p className={`note${foreign.length ? " warn" : ""}`}>
          {foreign.length > 0 && <>{foreign.length === reach.length ? (reach.length > 1 ? "These blocks were" : "This block was") : `The block in ${listOf(foreign.map((t) => t.label))} was`} written
            from {listOf([...new Set(foreign.map((t) => t.source!))])}, not from this folder. </>}
          {kept.length > 0
            ? `Nothing to link from here yet, so AgentBridge leaves ${kept.length > 1 ? "them" : "it"} alone. Unlink removes ${kept.length > 1 ? "one" : "it"}.`
            : "Link replaces it with the instructions here."}
        </p>
      )}
      {edited.length > 0 && (
        <p className="note warn">
          Someone edited the AgentBridge block in {listOf(edited.map((t) => t.path))} by hand, so saving here doesn't update it. Move those edits into these instructions, then{" "}
          <button className="link" disabled={busy || !!why} onClick={() => onApply(edited.map((t) => t.id), true)}>overwrite the block</button>.
        </p>
      )}
      <IssueList issues={issues} />
    </div>
  );
}

function NewSkill({ onClose, onCreated }: { onClose: () => void; onCreated: (r: { links: SkillLinkResult[] | null; state: SkillsState }, name: string) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [withWrapper, setWithWrapper] = useState(true);
  const [wrapperName, setWrapperName] = useState("");
  const [wrapperTouched, setWrapperTouched] = useState(false);
  const [tools, setTools] = useState("");
  const [linkNow, setLinkNow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const wName = wrapperTouched ? wrapperName : name ? `${name}-agent` : "";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await admin<{ links: SkillLinkResult[] | null; state: SkillsState }>("POST", "/skills", {
        name: name.trim(), description: description.trim(), wrapper_name: withWrapper ? wName.trim() : null, tools: tools.trim(), link: linkNow,
      });
      onCreated(r, name.trim());
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal title="New skill" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)}>
        <Field label="Skill name" hint={<>Lowercase letters, digits and hyphens. Creates <code>skills/{name || "<name>"}/SKILL.md</code>.</>}>
          <input value={name} onChange={(e) => setName(e.target.value)} required pattern={NAME_PATTERN} maxLength={64} placeholder="write-docs" autoComplete="off" />
        </Field>
        <Field label="Description" hint="Say what the skill does and when to use it. Agents read this to decide when to load the skill.">
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} required maxLength={1024} placeholder="Write and update docs for code changes. Use when the user asks to document a feature or update a README." />
        </Field>
        <label className="check" style={{ marginTop: 14 }}>
          <input type="checkbox" checked={withWrapper} onChange={(e) => setWithWrapper(e.target.checked)} />
          <span>Create a Claude Code wrapper so the skill can run as a subagent in its own context</span>
        </label>
        {withWrapper && (
          <div className="grid" style={{ marginTop: 12 }}>
            <Field label="Wrapper name" hint={<>Saved as <code>claude-agents/{wName || "<name>"}.md</code></>}>
              <input value={wName} onChange={(e) => { setWrapperTouched(true); setWrapperName(e.target.value); }} required pattern={NAME_PATTERN} maxLength={64} autoComplete="off" />
            </Field>
            <Field label="Tools (optional)" hint="Leave empty to allow every tool.">
              <input value={tools} onChange={(e) => setTools(e.target.value)} placeholder="Read, Grep, Glob, Bash" autoComplete="off" />
            </Field>
          </div>
        )}
        <label className="check" style={{ marginTop: 14 }}>
          <input type="checkbox" checked={linkNow} onChange={(e) => setLinkNow(e.target.checked)} />
          <span>Link it into Claude Code, Codex and Antigravity right away</span>
        </label>
        <ErrorNote message={error} />
        <div className="modal-foot">
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary" disabled={busy}>{busy ? "Creating…" : "Create skill"}</button>
        </div>
      </form>
    </Modal>
  );
}

function LinkResults({ results, onClose }: { results: SkillLinkResult[]; onClose: () => void }) {
  const changed = results.filter((r) => r.status !== "unchanged");
  const skipped = results.filter((r) => r.status === "skipped");
  const removed = results.filter((r) => r.status === "removed");
  const made = changed.length - skipped.length - removed.length;
  return (
    <Modal title="Linked into agents" onClose={onClose} wide>
      <p className={skipped.length ? "note warn" : "note ok"}>
        {changed.length ? [made && `${made} links created or updated.`, removed.length && `${removed.length} stale links removed (their skill was renamed or deleted).`].filter(Boolean).join(" ") : "Everything was already linked."}
        {skipped.length > 0 && ` ${skipped.length} skipped because a real file or folder is already there. Move it aside and link again.`}
      </p>
      {changed.length > 0 && (
        <ul className="plain">
          {changed.map((r) => (
            <li key={r.path} className="row nowrap">
              <Pill tone={r.status === "skipped" ? "warn" : r.status === "removed" ? "info" : "ok"}>{r.status}</Pill>
              <span className="mono small clip" title={r.path}>{r.path}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="modal-foot"><button className="primary" onClick={onClose}>Done</button></div>
    </Modal>
  );
}

// ---------------------------------------------------------------- preview

function inline(s: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    if (m[1] !== undefined) out.push(<code key={m.index}>{m[1]}</code>);
    else if (m[2] !== undefined) out.push(<strong key={m.index}>{m[2]}</strong>);
    else out.push(/^https?:\/\//.test(m[4]) ? <a key={m.index} href={m[4]} target="_blank" rel="noopener noreferrer">{m[3]}</a> : <span key={m.index}>{m[3]}</span>);
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

function splitFrontmatter(text: string): { fields: [string, string][] | null; body: string } {
  const m = text.replace(/\r\n/g, "\n").match(/^---\n([\s\S]*?)\n---[ \t]*(?:\n|$)([\s\S]*)$/);
  if (!m) return { fields: null, body: text };
  const fields: [string, string][] = [];
  const lines = m[1].split("\n");
  for (let i = 0; i < lines.length; ) {
    const kv = lines[i++].match(/^([\w-]+):\s*(.*)$/);
    if (!kv) continue;
    let v = kv[2].trim();
    if (/^[>|][+-]?$/.test(v)) {
      const block: string[] = [];
      while (i < lines.length && (/^\s/.test(lines[i]) || !lines[i].trim())) block.push(lines[i++].trim());
      v = v[0] === ">" ? block.join(" ").replace(/\s+/g, " ").trim() : block.join("\n").trim();
    } else if (/^(["']).*\1$/.test(v)) v = v.slice(1, -1);
    fields.push([kv[1], v]);
  }
  return { fields, body: m[2] };
}

function Preview({ text, plain, intro }: { text: string; plain?: boolean; intro?: string }) {
  const { fields, body } = plain ? { fields: null, body: text } : splitFrontmatter(text);
  const blocks: ReactNode[] = [];
  const lines = body.split("\n");
  let para: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (para.length) blocks.push(<p key={blocks.length}>{inline(para.join(" "))}</p>);
    if (list) {
      const items = list.items.map((it, n) => <li key={n}>{inline(it)}</li>);
      blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    }
    para = [];
    list = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flush();
      const code: string[] = [];
      while (++i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i]);
      blocks.push(<pre key={blocks.length}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      flush();
      const level = h[1].length;
      blocks.push(level === 1 ? <h1 key={blocks.length}>{inline(h[2])}</h1> : level === 2 ? <h2 key={blocks.length}>{inline(h[2])}</h2> : <h4 key={blocks.length}>{inline(h[2])}</h4>);
      continue;
    }
    const li = line.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
    if (li) {
      const ordered = /\d/.test(li[1]);
      if (para.length || (list && list.ordered !== ordered)) flush();
      list ??= { ordered, items: [] };
      list.items.push(li[2]);
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    if (list && /^\s+\S/.test(line)) { list.items[list.items.length - 1] += " " + line.trim(); continue; }
    if (list) flush();
    para.push(line.trim());
  }
  flush();
  return (
    <div className="skills-preview">
      {intro && <p className="muted small">{intro}</p>}
      {plain && !text.trim() && <p className="empty">Nothing yet.</p>}
      {plain ? null : fields ? (
        <dl className="skills-fm">
          {fields.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd className={k === "name" ? "mono" : undefined}>{v}{k === "description" && <span className="muted small"> · {v.length} / 1024 characters</span>}</dd>
            </div>
          ))}
        </dl>
      ) : <p className="note bad">This file has no frontmatter.</p>}
      {blocks}
    </div>
  );
}

// ---------------------------------------------------------------- diff

type Line = { t: "=" | "+" | "-"; l: string; a?: number; b?: number };

function lineDiff(a: string, b: string): Line[] {
  const A = a.split("\n"), B = b.split("\n");
  if (A.length * B.length > 4e6) return [...A.map((l, i) => ({ t: "-" as const, l, a: i + 1 })), ...B.map((l, i) => ({ t: "+" as const, l, b: i + 1 }))];
  const L = Array.from({ length: A.length + 1 }, () => new Int32Array(B.length + 1));
  for (let i = A.length - 1; i >= 0; i--) for (let j = B.length - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: Line[] = [];
  let i = 0, j = 0;
  while (i < A.length && j < B.length) {
    if (A[i] === B[j]) out.push({ t: "=", l: A[i], a: ++i, b: ++j });
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ t: "-", l: A[i], a: ++i });
    else out.push({ t: "+", l: B[j], b: ++j });
  }
  while (i < A.length) out.push({ t: "-", l: A[i], a: ++i });
  while (j < B.length) out.push({ t: "+", l: B[j], b: ++j });
  return out;
}

const diffCount = (a: string, b: string) => lineDiff(a, b).filter((d) => d.t !== "=").length;

function Diff({ a, b }: { a: string; b: string }) {
  const d = lineDiff(a, b);
  const keep = d.map(() => false);
  d.forEach((x, i) => { if (x.t !== "=") for (let k = Math.max(0, i - 3); k <= Math.min(d.length - 1, i + 3); k++) keep[k] = true; });
  const rows: ReactNode[] = [];
  let gap = false;
  d.forEach((x, i) => {
    if (!keep[i]) { if (!gap) rows.push(<div key={`g${i}`} className="skills-diff-gap">⋯</div>); gap = true; return; }
    gap = false;
    rows.push(
      <div key={i} className={`skills-diff-row ${x.t === "+" ? "add" : x.t === "-" ? "del" : ""}`}>
        <span className="ln">{x.t !== "+" ? x.a : ""}</span>
        <span className="ln">{x.t !== "-" ? x.b : ""}</span>
        <span aria-label={x.t === "+" ? "added" : x.t === "-" ? "removed" : undefined}>{x.t === "=" ? " " : x.t === "+" ? "+" : "−"}</span>
        <span>{x.l || " "}</span>
      </div>,
    );
  });
  return <div className="skills-diff mono">{rows}</div>;
}
