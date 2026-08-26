import type { ReactNode } from "react";

export function SectionCard(props: {
  title: ReactNode;
  subtitle?: string;
  tone?: "default" | "model" | "evidence" | "context";
  children: ReactNode;
}) {
  return (
    <section className={`card tone-${props.tone ?? "default"}`}>
      <div className="card-head">
        <h2>{props.title}</h2>
        {props.subtitle && <p className="muted small">{props.subtitle}</p>}
      </div>
      {props.children}
    </section>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}…
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      {hint && <p className="muted">{hint}</p>}
    </div>
  );
}

export function KV({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="kv">
      <span className="k">{k}</span>
      <span className={mono ? "v mono" : "v"}>{v ?? "—"}</span>
    </div>
  );
}
