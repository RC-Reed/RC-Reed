import { useState } from "react";

import { PageHeader } from "../components/Layout";
import { Badge, Button, Card, ErrorNote, Field, Spinner, StatTile, inputClass } from "../components/ui";
import { shortDate, titleize } from "../lib/format";
import { del, patch, post } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { Project, Task } from "../lib/types";

const AREAS = ["work", "personal", "finance", "health", "home", "learning"];
const PRIORITY_LABEL: Record<number, string> = { 1: "P1", 2: "P2", 3: "P3", 4: "P4" };

export default function Tasks() {
  const [area, setArea] = useState("");
  const [showDone, setShowDone] = useState(false);
  const path = `/tasks?open_only=${!showDone}${area ? `&area=${area}` : ""}`;
  const tasks = useApi<Task[]>(path, [area, showDone]);
  const projects = useApi<Project[]>("/projects");
  const [adding, setAdding] = useState(false);

  const open = (tasks.data ?? []).filter((task) => task.status !== "done" && task.status !== "cancelled");
  const overdue = open.filter((task) => task.due_at && new Date(task.due_at) < new Date());
  const projectName = (id: string | null) =>
    (projects.data ?? []).find((project) => project.id === id)?.name ?? null;

  async function setStatus(task: Task, status: string) {
    await patch(`/tasks/${task.id}`, { status });
    tasks.reload();
  }

  async function remove(task: Task) {
    await del(`/tasks/${task.id}`);
    tasks.reload();
  }

  // Group by due bucket — the way you'd actually triage a list.
  const groups: { label: string; items: Task[] }[] = [
    { label: "Overdue", items: [] },
    { label: "Today", items: [] },
    { label: "This week", items: [] },
    { label: "Later", items: [] },
    { label: "No date", items: [] },
  ];
  const now = new Date();
  const endOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
  const endOfWeek = new Date(endOfToday.getTime() + 6 * 86_400_000);

  for (const task of tasks.data ?? []) {
    if (!task.due_at) groups[4].items.push(task);
    else {
      const due = new Date(task.due_at);
      if (due < now && task.status !== "done") groups[0].items.push(task);
      else if (due <= endOfToday) groups[1].items.push(task);
      else if (due <= endOfWeek) groups[2].items.push(task);
      else groups[3].items.push(task);
    }
  }

  return (
    <>
      <PageHeader
        title="Tasks"
        subtitle="Work items, personal todos and anything a connector pushed in."
        action={
          <Button variant="primary" onClick={() => setAdding((value) => !value)}>
            {adding ? "Cancel" : "New task"}
          </Button>
        }
      />

      {adding && (
        <AddTaskForm
          projects={projects.data ?? []}
          onDone={() => {
            setAdding(false);
            tasks.reload();
          }}
        />
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <StatTile label="Open" value={String(open.length)} />
        <StatTile
          label="Overdue"
          value={String(overdue.length)}
          tone={overdue.length > 0 ? "critical" : "good"}
        />
        <StatTile label="Projects" value={String((projects.data ?? []).length)} />
      </div>

      <Card
        title="Your list"
        action={
          <div className="flex items-center gap-2">
            <select
              className="rounded-lg border border-ink-600 bg-ink-850 px-2.5 py-1 text-xs text-slate-100 focus:border-series-1 focus:outline-none"
              value={area}
              onChange={(event) => setArea(event.target.value)}
            >
              <option value="">All areas</option>
              {AREAS.map((option) => (
                <option key={option} value={option}>
                  {titleize(option)}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-xs text-muted">
              <input
                type="checkbox"
                className="accent-series-1"
                checked={showDone}
                onChange={(event) => setShowDone(event.target.checked)}
              />
              Show done
            </label>
          </div>
        }
      >
        {tasks.loading && <Spinner />}
        {tasks.error && <ErrorNote message={tasks.error} onRetry={tasks.reload} />}
        {!tasks.loading && (tasks.data ?? []).length === 0 && (
          <p className="py-8 text-center text-xs text-muted">Nothing here. Enjoy the quiet.</p>
        )}

        <div className="space-y-6">
          {groups
            .filter((group) => group.items.length > 0)
            .map((group) => (
              <div key={group.label}>
                <h3
                  className={`mb-2 text-[11px] font-semibold uppercase tracking-wider ${
                    group.label === "Overdue" ? "text-status-critical" : "text-muted"
                  }`}
                >
                  {group.label} · {group.items.length}
                </h3>
                <ul className="space-y-1.5">
                  {group.items.map((task) => (
                    <li
                      key={task.id}
                      className="group flex items-center gap-3 rounded-lg border border-ink-750 bg-ink-850 px-3 py-2.5"
                    >
                      <input
                        type="checkbox"
                        aria-label={`Complete ${task.title}`}
                        className="h-4 w-4 shrink-0 accent-series-1"
                        checked={task.status === "done"}
                        onChange={(event) => setStatus(task, event.target.checked ? "done" : "todo")}
                      />
                      <div className="min-w-0 flex-1">
                        <p
                          className={`truncate text-sm ${
                            task.status === "done" ? "text-muted line-through" : "text-slate-200"
                          }`}
                        >
                          {task.url ? (
                            <a
                              href={task.url}
                              target="_blank"
                              rel="noreferrer"
                              className="hover:text-series-1 hover:underline"
                            >
                              {task.title}
                            </a>
                          ) : (
                            task.title
                          )}
                        </p>
                        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-muted">
                          <span
                            className={
                              task.priority === 1 ? "font-medium text-status-critical" : undefined
                            }
                          >
                            {PRIORITY_LABEL[task.priority]}
                          </span>
                          <span className="capitalize">{task.area}</span>
                          {projectName(task.project_id) &&
                            projectName(task.project_id)!.toLowerCase() !== task.area && (
                              <span>· {projectName(task.project_id)}</span>
                            )}
                          {task.due_at && <span>· {shortDate(task.due_at)}</span>}
                          {task.source !== "manual" && <Badge>{task.source}</Badge>}
                        </div>
                      </div>
                      <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                        {task.status !== "in_progress" && task.status !== "done" && (
                          <Button variant="ghost" onClick={() => setStatus(task, "in_progress")}>
                            Start
                          </Button>
                        )}
                        <Button variant="ghost" onClick={() => remove(task)}>
                          Delete
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </div>
      </Card>
    </>
  );
}

function AddTaskForm({ projects, onDone }: { projects: Project[]; onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [area, setArea] = useState("personal");
  const [priority, setPriority] = useState(3);
  const [dueAt, setDueAt] = useState("");
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await post("/tasks", {
        title,
        area,
        priority,
        project_id: projectId || null,
        // The date input gives a local calendar date; anchor it to 9am so it
        // doesn't land at midnight UTC and read as the previous day.
        due_at: dueAt ? new Date(`${dueAt}T09:00:00`).toISOString() : null,
      });
      onDone();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  return (
    <Card title="New task" className="mb-6">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-5">
        <div className="sm:col-span-2">
          <Field label="Title">
            <input
              required
              className={inputClass}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Area">
          <select className={inputClass} value={area} onChange={(e) => setArea(e.target.value)}>
            {AREAS.map((option) => (
              <option key={option} value={option}>
                {titleize(option)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Priority">
          <select
            className={inputClass}
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
          >
            {[1, 2, 3, 4].map((option) => (
              <option key={option} value={option}>
                {PRIORITY_LABEL[option]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Due">
          <input type="date" className={inputClass} value={dueAt} onChange={(e) => setDueAt(e.target.value)} />
        </Field>
        {projects.length > 0 && (
          <Field label="Project">
            <select
              className={inputClass}
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">None</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        {error && <p className="col-span-full text-xs text-status-critical">{error}</p>}
        <div className="col-span-full">
          <Button type="submit" variant="primary">
            Add task
          </Button>
        </div>
      </form>
    </Card>
  );
}
