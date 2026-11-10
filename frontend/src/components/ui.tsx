import { ReactNode, useEffect, useRef, useState } from "react";

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, select, textarea, button.primary")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="ghost icon" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Replaces window.confirm(): the caller renders it while a destructive action is pending. */
export function Confirm({ title, body, action, onConfirm, onCancel }: { title: string; body: ReactNode; action: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <Modal title={title} onClose={onCancel}>
      <p>{body}</p>
      <div className="modal-foot">
        <button className="ghost" onClick={onCancel}>
          Cancel
        </button>
        <button className="danger" onClick={onConfirm}>
          {action}
        </button>
      </div>
    </Modal>
  );
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Pill({ tone, children, title }: { tone?: "ok" | "bad" | "warn" | "info"; children: ReactNode; title?: string }) {
  return (
    <span className={`pill ${tone ?? ""}`} title={title}>
      {tone && <span className="dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="ghost small"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard blocked: the text stays selectable */
        }
      }}
    >
      {done ? "Copied ✓" : label}
    </button>
  );
}

export function Code({ children, copy = true }: { children: string; copy?: boolean }) {
  return (
    <div className="code">
      {copy && <CopyButton text={children} />}
      <pre>{children}</pre>
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorNote({ message }: { message: string }) {
  return message ? (
    <p className="note bad" role="alert">
      {message}
    </p>
  ) : null;
}
