import { useEffect, useState } from "react";

import { MetricChart, Sparkline } from "../components/charts";
import { PageHeader } from "../components/Layout";
import { Button, Card, ErrorNote, Field, Spinner, inputClass } from "../components/ui";
import { metricValue, number, shortDate, titleize } from "../lib/format";
import { get, post } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { HealthMetricSummary, SeriesPoint } from "../lib/types";

type Workout = {
  id: string;
  activity: string;
  started_at: string;
  duration_minutes: number;
  distance_miles: number | null;
  energy_kcal: number | null;
  avg_heart_rate: number | null;
};

type SummaryResponse = {
  metrics: HealthMetricSummary[];
  available: string[];
  workouts: Workout[];
};

export default function Health() {
  const summary = useApi<SummaryResponse>("/health/summary");
  const [selected, setSelected] = useState<string | null>(null);
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [sparks, setSparks] = useState<Record<string, SeriesPoint[]>>({});
  const [adding, setAdding] = useState(false);

  const metrics = summary.data?.metrics ?? [];
  const active = selected ?? metrics[0]?.metric ?? null;

  useEffect(() => {
    if (!active) return;
    get<SeriesPoint[]>(`/health/series/${active}?days=90`).then(setSeries).catch(() => setSeries([]));
  }, [active]);

  useEffect(() => {
    // Small 30-day series behind each tile, fetched once per metric set.
    if (!metrics.length) return;
    let cancelled = false;
    Promise.all(
      metrics.map((metric) =>
        get<SeriesPoint[]>(`/health/series/${metric.metric}?days=30`)
          .then((points) => [metric.metric, points] as const)
          .catch(() => [metric.metric, []] as const),
      ),
    ).then((entries) => {
      if (!cancelled) setSparks(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, [summary.data]);

  const activeMeta = metrics.find((metric) => metric.metric === active);
  const formatter = (value: number) =>
    active === "sleep_duration" ? `${(value / 60).toFixed(1)}h` : number(value, value < 100 ? 1 : 0);

  return (
    <>
      <PageHeader
        title="Health"
        subtitle="Pushed from your iPhone, or entered by hand for anything offline."
        action={
          <Button variant="primary" onClick={() => setAdding((value) => !value)}>
            {adding ? "Cancel" : "Log a reading"}
          </Button>
        }
      />

      {adding && (
        <AddMetricForm
          available={summary.data?.available ?? []}
          onDone={() => {
            setAdding(false);
            summary.reload();
          }}
        />
      )}

      {summary.loading && <Spinner />}
      {summary.error && <ErrorNote message={summary.error} onRetry={summary.reload} />}

      {!summary.loading && metrics.length === 0 && (
        <Card>
          <div className="py-8 text-center">
            <p className="text-sm text-slate-300">No health data yet.</p>
            <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-muted">
              Add the Apple Health connector under Connections, then either point the
              "Health Auto Export" iOS app at your ingest endpoint, or upload an
              export.xml from the Health app to backfill history.
            </p>
          </div>
        </Card>
      )}

      {metrics.length > 0 && (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {metrics.map((metric) => {
              const isActive = metric.metric === active;
              return (
                <button
                  key={metric.metric}
                  onClick={() => setSelected(metric.metric)}
                  className={`rounded-xl border px-5 py-4 text-left transition-colors ${
                    isActive
                      ? "border-series-1 bg-series-1/10"
                      : "border-ink-700 bg-ink-800 hover:border-ink-600"
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-[11px] font-medium uppercase tracking-wider text-muted">
                        {metric.label}
                      </p>
                      <p className="tabular mt-1.5 text-2xl font-semibold text-slate-100">
                        {metricValue(metric.metric, metric.value, metric.unit)}
                      </p>
                    </div>
                    {metric.change_pct !== null && metric.direction !== "flat" && (
                      <span
                        className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                          metric.direction === "up"
                            ? "bg-status-good/10 text-status-good"
                            : "bg-status-warning/10 text-status-warning"
                        }`}
                      >
                        {metric.change_pct > 0 ? "+" : ""}
                        {metric.change_pct.toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <div className="mt-3">
                    <Sparkline
                      data={sparks[metric.metric] ?? []}
                      tone={isActive ? "var(--series-1)" : "var(--series-3)"}
                    />
                  </div>
                  <p className="mt-1 text-[11px] text-muted">
                    7-day avg{" "}
                    {metric.avg_7d === null
                      ? "—"
                      : metricValue(metric.metric, metric.avg_7d, metric.unit)}{" "}
                    · last {shortDate(metric.recorded_on)}
                  </p>
                </button>
              );
            })}
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-3">
            <Card
              title={activeMeta?.label ?? "Trend"}
              subtitle="Last 90 days"
              className="lg:col-span-2"
            >
              <MetricChart
                data={series}
                label={activeMeta?.label ?? ""}
                format={formatter}
                height={260}
              />
            </Card>

            <Card title="Recent workouts">
              {(summary.data?.workouts ?? []).length === 0 ? (
                <p className="py-6 text-center text-xs text-muted">No workouts recorded.</p>
              ) : (
                <ul className="divide-y divide-ink-750">
                  {(summary.data?.workouts ?? []).map((workout) => (
                    <li key={workout.id} className="py-2.5">
                      <div className="flex items-baseline justify-between">
                        <span className="text-sm capitalize text-slate-200">{workout.activity}</span>
                        <span className="tabular text-xs text-muted">
                          {workout.duration_minutes.toFixed(0)} min
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-muted">
                        {shortDate(workout.started_at)}
                        {workout.distance_miles ? ` · ${workout.distance_miles.toFixed(2)} mi` : ""}
                        {workout.energy_kcal ? ` · ${workout.energy_kcal.toFixed(0)} kcal` : ""}
                        {workout.avg_heart_rate ? ` · ${workout.avg_heart_rate.toFixed(0)} bpm` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}

function AddMetricForm({ available, onDone }: { available: string[]; onDone: () => void }) {
  const options = available.length
    ? available
    : ["weight", "steps", "resting_heart_rate", "sleep_duration", "blood_pressure_systolic"];
  const [metric, setMetric] = useState(options[0]);
  const [value, setValue] = useState("");
  const [recordedOn, setRecordedOn] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await post("/health/metrics", {
        metric,
        value: Number(value),
        recorded_on: recordedOn,
        source: "manual",
      });
      onDone();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  return (
    <Card title="Log a reading" subtitle="For a scale, a cuff, anything not on your phone." className="mb-6">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-4">
        <Field label="Metric">
          <select className={inputClass} value={metric} onChange={(e) => setMetric(e.target.value)}>
            {options.map((option) => (
              <option key={option} value={option}>
                {titleize(option)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Value">
          <input
            required
            type="number"
            step="0.01"
            className={inputClass}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </Field>
        <Field label="Date">
          <input
            type="date"
            className={inputClass}
            value={recordedOn}
            onChange={(e) => setRecordedOn(e.target.value)}
          />
        </Field>
        {error && <p className="col-span-full text-xs text-status-critical">{error}</p>}
        <div className="col-span-full">
          <Button type="submit" variant="primary">
            Save reading
          </Button>
        </div>
      </form>
    </Card>
  );
}
