import { useRef, useState } from "react";

import { PageHeader } from "../components/Layout";
import { Badge, Button, Card, ErrorNote, Field, Spinner, inputClass } from "../components/ui";
import { titleize } from "../lib/format";
import { del, get, patch, post, upload } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { Connection, Connector, ConnectorField, SyncRun } from "../lib/types";

const CATEGORY_ORDER = ["finance", "health", "productivity", "work", "other"];

export default function Connections() {
  const connectors = useApi<Connector[]>("/connectors");
  const connections = useApi<Connection[]>("/connections");
  const [installing, setInstalling] = useState<Connector | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const grouped = CATEGORY_ORDER.map((category) => ({
    category,
    items: (connectors.data ?? []).filter((connector) => connector.category === category),
  })).filter((group) => group.items.length > 0);

  return (
    <>
      <PageHeader
        title="Connections"
        subtitle="Every source of data. Adding an integration is a form, not a deploy."
      />

      {message && (
        <p className="mb-4 rounded-lg border border-ink-700 bg-ink-800 px-4 py-2.5 text-xs text-muted">
          {message}
        </p>
      )}

      {installing && (
        <ConnectorSetup
          connector={installing}
          onCancel={() => setInstalling(null)}
          onDone={() => {
            setInstalling(null);
            connections.reload();
            setMessage(`${installing.name} added.`);
          }}
        />
      )}

      <Card title="Installed" subtitle={`${(connections.data ?? []).length} configured`} className="mb-6">
        {connections.loading && <Spinner />}
        {connections.error && <ErrorNote message={connections.error} onRetry={connections.reload} />}
        {!connections.loading && (connections.data ?? []).length === 0 && (
          <p className="py-6 text-center text-xs text-muted">
            Nothing connected yet. Pick something from the catalogue below.
          </p>
        )}
        <div className="space-y-3">
          {(connections.data ?? []).map((connection) => (
            <ConnectionRow
              key={connection.id}
              connection={connection}
              onChanged={connections.reload}
              onMessage={setMessage}
            />
          ))}
        </div>
      </Card>

      <IngestPanel />

      <h2 className="mb-3 mt-8 text-sm font-semibold text-slate-100">Catalogue</h2>
      {connectors.loading && <Spinner />}
      {grouped.map((group) => (
        <div key={group.category} className="mb-6">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
            {titleize(group.category)}
          </h3>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {group.items.map((connector) => (
              <div
                key={connector.slug}
                className="flex flex-col rounded-xl border border-ink-700 bg-ink-800 p-4"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <h4 className="text-sm font-medium text-slate-100">{connector.name}</h4>
                  <Badge tone={connector.mode === "push" ? "warning" : "accent"}>
                    {connector.mode === "push" ? "upload / push" : "auto sync"}
                  </Badge>
                </div>
                <p className="flex-1 text-xs leading-relaxed text-muted">{connector.description}</p>
                <div className="mt-3 flex flex-wrap gap-1">
                  {connector.provides.map((item) => (
                    <Badge key={item}>{item.replace(/_/g, " ")}</Badge>
                  ))}
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <Button variant="primary" onClick={() => setInstalling(connector)}>
                    Add
                  </Button>
                  {connector.docs_url && (
                    <a
                      href={connector.docs_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-muted hover:text-series-1 hover:underline"
                    >
                      Setup docs ↗
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

function ConnectionRow({
  connection,
  onChanged,
  onMessage,
}: {
  connection: Connection;
  onChanged: () => void;
  onMessage: (value: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState<SyncRun[] | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const isPush = connection.connector?.mode === "push";

  const statusTone =
    connection.status === "active"
      ? "good"
      : connection.status === "error"
        ? "critical"
        : "warning";

  async function syncNow() {
    setBusy(true);
    try {
      const run = await post<SyncRun>(`/connections/${connection.id}/sync`);
      onMessage(`${connection.display_name}: ${run.message || run.status}`);
      onChanged();
    } catch (cause) {
      onMessage((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const run = await upload<SyncRun>(`/connections/${connection.id}/ingest`, file);
      onMessage(`${connection.display_name}: ${run.message || run.status}`);
      onChanged();
    } catch (cause) {
      onMessage((cause as Error).message);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function toggle() {
    await patch(`/connections/${connection.id}`, { is_enabled: !connection.is_enabled });
    onChanged();
  }

  async function remove() {
    if (!confirm(`Remove "${connection.display_name}"? Imported data stays; the link is deleted.`)) return;
    await del(`/connections/${connection.id}`);
    onChanged();
  }

  async function loadRuns() {
    if (runs) return setRuns(null);
    setRuns(await get<SyncRun[]>(`/connections/${connection.id}/runs?limit=10`));
  }

  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-medium text-slate-100">{connection.display_name}</h4>
            <Badge tone={statusTone}>{connection.status.replace(/_/g, " ")}</Badge>
            {!connection.is_enabled && <Badge>paused</Badge>}
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {connection.connector?.name ?? connection.connector_slug}
            {connection.last_sync_at
              ? ` · last run ${new Date(connection.last_sync_at).toLocaleString()}`
              : " · never run"}
            {!isPush && ` · every ${connection.sync_interval_minutes} min`}
          </p>
          {connection.last_error && (
            <p className="mt-1.5 rounded border border-status-critical/30 bg-status-critical/10 px-2 py-1 text-xs text-status-critical">
              {connection.last_error}
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {isPush ? (
            <>
              <input
                ref={fileInput}
                type="file"
                accept=".csv,.xml,.json,.txt"
                className="hidden"
                onChange={handleFile}
              />
              <Button onClick={() => fileInput.current?.click()} disabled={busy}>
                {busy ? "Importing…" : "Upload file"}
              </Button>
            </>
          ) : (
            <Button onClick={syncNow} disabled={busy}>
              {busy ? "Syncing…" : "Sync now"}
            </Button>
          )}
          <Button variant="ghost" onClick={loadRuns}>
            {runs ? "Hide log" : "History"}
          </Button>
          <Button variant="ghost" onClick={toggle}>
            {connection.is_enabled ? "Pause" : "Resume"}
          </Button>
          <Button variant="danger" onClick={remove}>
            Remove
          </Button>
        </div>
      </div>

      {runs && (
        <div className="mt-3 overflow-x-auto rounded border border-ink-700">
          <table className="w-full text-xs">
            <thead className="bg-ink-800 text-left text-muted">
              <tr>
                <th className="px-3 py-1.5 font-medium">When</th>
                <th className="px-3 py-1.5 font-medium">Status</th>
                <th className="px-3 py-1.5 font-medium">Records</th>
                <th className="px-3 py-1.5 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-750">
              {runs.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-3 text-center text-muted">
                    No runs recorded yet.
                  </td>
                </tr>
              )}
              {runs.map((run) => (
                <tr key={run.id}>
                  <td className="whitespace-nowrap px-3 py-1.5 text-muted">
                    {new Date(run.started_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge
                      tone={
                        run.status === "success"
                          ? "good"
                          : run.status === "failed"
                            ? "critical"
                            : "warning"
                      }
                    >
                      {run.status}
                    </Badge>
                  </td>
                  <td className="tabular px-3 py-1.5 text-muted">
                    +{run.created_count} / ~{run.updated_count}
                  </td>
                  <td className="px-3 py-1.5 text-muted">{run.message || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ConnectorSetup({
  connector,
  onCancel,
  onDone,
}: {
  connector: Connector;
  onCancel: () => void;
  onDone: () => void;
}) {
  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(
      connector.fields.map((field) => [
        field.key,
        field.type === "checkbox" ? Boolean(field.default) : String(field.default ?? ""),
      ]),
    ),
  );
  const [displayName, setDisplayName] = useState(connector.name);
  const [interval, setInterval] = useState(60);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const config: Record<string, unknown> = {};
    const secrets: Record<string, unknown> = {};
    for (const field of connector.fields) {
      const value = values[field.key];
      if (field.secret) secrets[field.key] = value;
      else config[field.key] = field.type === "number" ? Number(value) : value;
    }

    try {
      await post("/connections", {
        connector_slug: connector.slug,
        display_name: displayName,
        config,
        secrets,
        sync_interval_minutes: interval,
      });
      onDone();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title={`Set up ${connector.name}`}
      subtitle={connector.description}
      className="mb-6 border-series-1/40"
    >
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Name this connection" help="Useful when you add more than one of the same type.">
          <input
            className={inputClass}
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </Field>

        {connector.schedulable && (
          <Field label="Sync every (minutes)" help="Minimum 5. The scheduler honours this per connection.">
            <input
              type="number"
              min={5}
              className={inputClass}
              value={interval}
              onChange={(event) => setInterval(Number(event.target.value))}
            />
          </Field>
        )}

        {connector.fields.map((field) => (
          <ConnectorInput
            key={field.key}
            field={field}
            value={values[field.key]}
            onChange={(value) => setValues((current) => ({ ...current, [field.key]: value }))}
          />
        ))}

        {error && <p className="col-span-full text-xs text-status-critical">{error}</p>}

        <div className="col-span-full flex gap-2">
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Saving…" : "Add connection"}
          </Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}

function ConnectorInput({
  field,
  value,
  onChange,
}: {
  field: ConnectorField;
  value: string | boolean;
  onChange: (value: string | boolean) => void;
}) {
  if (field.type === "checkbox") {
    return (
      <label className="flex items-center gap-2 self-end pb-2 text-xs text-muted">
        <input
          type="checkbox"
          className="accent-series-1"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>
          {field.label}
          {field.help && <span className="ml-1 opacity-70">— {field.help}</span>}
        </span>
      </label>
    );
  }

  return (
    <Field
      label={`${field.label}${field.required ? "" : " (optional)"}`}
      help={field.secret ? `${field.help} Stored encrypted; never shown again.`.trim() : field.help}
    >
      {field.type === "select" ? (
        <select
          className={inputClass}
          value={String(value)}
          onChange={(event) => onChange(event.target.value)}
        >
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.secret || field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
          required={field.required}
          autoComplete="off"
          className={inputClass}
          value={String(value)}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  );
}

function IngestPanel() {
  const info = useApi<{ endpoint: string; token: string; header: string; note: string }>(
    "/system/ingest-info",
  );
  const [revealed, setRevealed] = useState(false);

  if (!info.data) return null;

  return (
    <Card
      title="Device push endpoint"
      subtitle="Point an iPhone automation here to stream health data in."
    >
      <dl className="space-y-3 text-xs">
        <div>
          <dt className="text-muted">URL</dt>
          <dd className="mt-1 break-all rounded border border-ink-700 bg-ink-850 px-3 py-2 font-mono text-slate-200">
            {info.data.endpoint}
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-2 text-muted">
            Header <span className="font-mono text-slate-300">{info.data.header}</span>
          </dt>
          <dd className="mt-1 flex items-center gap-2">
            <code className="flex-1 break-all rounded border border-ink-700 bg-ink-850 px-3 py-2 font-mono text-slate-200">
              {revealed ? info.data.token : "•".repeat(32)}
            </code>
            <Button onClick={() => setRevealed((value) => !value)}>
              {revealed ? "Hide" : "Reveal"}
            </Button>
            <Button onClick={() => navigator.clipboard?.writeText(info.data!.token)}>Copy</Button>
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-muted">{info.data.note}</p>
    </Card>
  );
}
