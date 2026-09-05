import { NavLink, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";

import { setToken } from "../lib/api";

const NAV = [
  { to: "/", label: "Overview", end: true, icon: "◧" },
  { to: "/money", label: "Money", icon: "◈" },
  { to: "/debt", label: "Debt", icon: "◑" },
  { to: "/investments", label: "Investments", icon: "◭" },
  { to: "/bills", label: "Bills & Subs", icon: "◫" },
  { to: "/tasks", label: "Tasks", icon: "☑" },
  { to: "/health", label: "Health", icon: "♡" },
  { to: "/connections", label: "Connections", icon: "⇄" },
];

export function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen bg-ink-900">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-ink-700 bg-ink-850 md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-series-1 text-sm font-bold text-white">
            L
          </span>
          <div>
            <p className="text-sm font-semibold leading-tight text-slate-100">Life OS</p>
            <p className="text-[10px] uppercase tracking-wider text-ink-500">self-hosted</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-series-1/15 font-medium text-series-1"
                    : "text-muted hover:bg-ink-800 hover:text-slate-200"
                }`
              }
            >
              <span aria-hidden="true" className="w-4 text-center text-xs opacity-70">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-ink-700 p-3">
          <button
            onClick={() => {
              setToken(null);
              navigate("/login");
            }}
            className="w-full rounded-lg px-3 py-2 text-left text-xs text-muted transition-colors hover:bg-ink-800 hover:text-slate-200"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Mobile nav: the sidebar collapses to a scrollable strip. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <nav className="flex gap-1 overflow-x-auto border-b border-ink-700 bg-ink-850 px-3 py-2 md:hidden">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-lg px-3 py-1.5 text-xs ${
                  isActive ? "bg-series-1/15 text-series-1" : "text-muted"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-50">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}
