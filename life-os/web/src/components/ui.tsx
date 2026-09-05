import type { ReactNode } from "react";

export function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-ink-700 bg-ink-800 shadow-lg shadow-black/20 ${className}`}
    >
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-ink-700 px-5 py-3.5">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: ReactNode;
  tone?: "neutral" | "good" | "warning" | "critical";
}) {
  const toneClass = {
    neutral: "text-slate-100",
    good: "text-status-good",
    warning: "text-status-warning",
    critical: "text-status-critical",
  }[tone];

  return (
    <div className="rounded-xl border border-ink-700 bg-ink-800 px-5 py-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className={`tabular mt-1.5 text-2xl font-semibold ${toneClass}`}>{value}</p>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function Button({
  children,
  onClick,
  type = "button",
  variant = "secondary",
  disabled,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "secondary" | "ghost" | "danger";
  disabled?: boolean;
  className?: string;
}) {
  const variants = {
    primary: "bg-series-1 text-white hover:bg-[#2f74cc] disabled:bg-ink-600",
    secondary: "border border-ink-600 bg-ink-750 text-slate-200 hover:bg-ink-700",
    ghost: "text-muted hover:text-slate-100 hover:bg-ink-750",
    danger: "border border-status-critical/40 text-status-critical hover:bg-status-critical/10",
  }[variant];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${variants} ${className}`}
    >
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warning" | "critical" | "accent";
}) {
  const tones = {
    neutral: "border-ink-600 bg-ink-750 text-muted-strong",
    good: "border-status-good/40 bg-status-good/10 text-status-good",
    warning: "border-status-warning/40 bg-status-warning/10 text-status-warning",
    critical: "border-status-critical/40 bg-status-critical/10 text-status-critical",
    accent: "border-series-1/40 bg-series-1/10 text-series-1",
  }[tone];
  return (
    <span
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${tones}`}
    >
      {children}
    </span>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-ink-600 px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-300">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-xs text-muted">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-xs text-muted" role="status">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-ink-500 border-t-series-1" />
      {label}…
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-status-critical/40 bg-status-critical/10 px-4 py-3 text-xs text-status-critical">
      <span>{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="font-medium underline underline-offset-2">
          Retry
        </button>
      )}
    </div>
  );
}

export function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-muted-strong">{label}</span>
      {children}
      {help && <span className="mt-1 block text-[11px] leading-snug text-muted">{help}</span>}
    </label>
  );
}

export const inputClass =
  "mt-1 w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-slate-100 placeholder:text-ink-500 focus:border-series-1 focus:outline-none focus:ring-1 focus:ring-series-1";
