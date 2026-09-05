/** Chart set.
 *
 * Rules held to throughout: one y-axis per chart (never dual), recessive
 * grid/axes, thin marks, a legend whenever two or more series share a plot,
 * and a hover tooltip on every plotted form. Series colors come from CSS
 * custom properties (--series-N) so the palette lives in one place.
 */

import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { money, moneyShort, monthLabel, number, shortDate } from "../lib/format";
import type { CashFlowPoint, NetWorthPoint, SeriesPoint, SpendingSlice } from "../lib/types";

const GRID = "var(--grid)";
const AXIS_TICK = { fill: "var(--text-secondary)", fontSize: 11 };
const SURFACE = "var(--surface-1)";

function TooltipShell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-xs shadow-xl">
      <p className="mb-1 font-medium text-slate-200">{label}</p>
      {children}
    </div>
  );
}

function Row({ color, name, value }: { color?: string; name: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="flex items-center gap-1.5 text-muted">
        {color && <span className="h-2 w-2 rounded-sm" style={{ background: color }} />}
        {name}
      </span>
      <span className="tabular font-medium text-slate-100">{value}</span>
    </div>
  );
}

/** A legend rendered as HTML rather than SVG, so it wraps and stays selectable. */
export function Legend({ items }: { items: { name: string; color: string }[] }) {
  return (
    <ul className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1">
      {items.map((item) => (
        <li key={item.name} className="flex items-center gap-1.5 text-[11px] text-muted">
          <span className="h-2 w-2 rounded-sm" style={{ background: item.color }} />
          {item.name}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
export function NetWorthChart({ data, height = 220 }: { data: NetWorthPoint[]; height?: number }) {
  if (data.length < 2) return <NoData hint="Net worth history builds up as connections sync." />;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="nw-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--series-1)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--series-1)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={shortDate}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          minTickGap={40}
        />
        <YAxis
          tickFormatter={moneyShort}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={56}
        />
        <Tooltip
          cursor={{ stroke: "var(--text-secondary)", strokeWidth: 1, strokeDasharray: "3 3" }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as NetWorthPoint;
            return (
              <TooltipShell label={shortDate(point.date)}>
                <Row color="var(--series-1)" name="Net worth" value={money(point.net_worth)} />
                <Row name="Assets" value={money(point.assets)} />
                <Row name="Liabilities" value={money(point.liabilities)} />
              </TooltipShell>
            );
          }}
        />
        <Area
          type="monotone"
          dataKey="net_worth"
          stroke="var(--series-1)"
          strokeWidth={2}
          fill="url(#nw-fill)"
          activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
export function CashFlowChart({ data, height = 200 }: { data: CashFlowPoint[]; height?: number }) {
  if (!data.length) return <NoData hint="Import transactions to see income against spending." />;

  return (
    <>
      <Legend
        items={[
          { name: "Income", color: "var(--series-1)" },
          { name: "Spending", color: "var(--series-2)" },
        ]}
      />
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} barGap={2}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="month"
            tickFormatter={monthLabel}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={{ stroke: GRID }}
          />
          <YAxis
            tickFormatter={moneyShort}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={56}
          />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const point = payload[0].payload as CashFlowPoint;
              return (
                <TooltipShell label={point.month}>
                  <Row color="var(--series-1)" name="Income" value={money(point.income)} />
                  <Row color="var(--series-2)" name="Spending" value={money(point.spending)} />
                  <Row name="Net" value={money(point.net)} />
                </TooltipShell>
              );
            }}
          />
          <Bar dataKey="income" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={22} />
          <Bar dataKey="spending" fill="var(--series-2)" radius={[4, 4, 0, 0]} maxBarSize={22} />
        </BarChart>
      </ResponsiveContainer>
    </>
  );
}

// ---------------------------------------------------------------------------
/** Ranked spending. One measure, one hue — category is the axis, not a color. */
export function SpendingBars({ data }: { data: SpendingSlice[] }) {
  if (!data.length) return <NoData hint="No spending recorded in this window." />;
  const max = Math.max(...data.map((slice) => slice.amount));

  return (
    <ul className="space-y-2.5">
      {data.map((slice) => (
        <li key={slice.category}>
          <div className="mb-1 flex items-baseline justify-between text-xs">
            <span className="capitalize text-slate-300">{slice.category.replace(/_/g, " ")}</span>
            <span className="tabular text-muted">
              {money(slice.amount)}
              <span className="ml-2 text-ink-500">{slice.share.toFixed(0)}%</span>
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-750">
            <div
              className="h-full rounded-full bg-series-1"
              style={{ width: `${Math.max((slice.amount / max) * 100, 2)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
/** Allocation as one stacked bar. Segments carry a 2px surface gap so adjacent
 *  fills stay separable, and every segment is direct-labeled below. */
export function AllocationBar({
  data,
}: {
  data: { asset_class: string; value: number; share: number }[];
}) {
  if (!data.length) return <NoData hint="Import holdings to see your allocation." />;
  const colors = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
  const shown = data.slice(0, 4);
  const rest = data.slice(4);
  const segments = rest.length
    ? [
        ...shown,
        {
          asset_class: "other",
          value: rest.reduce((sum, item) => sum + item.value, 0),
          share: rest.reduce((sum, item) => sum + item.share, 0),
        },
      ]
    : shown;

  return (
    <div>
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full">
        {segments.map((segment, index) => (
          <div
            key={segment.asset_class}
            className="h-full first:rounded-l-full last:rounded-r-full"
            style={{
              width: `${Math.max(segment.share, 1)}%`,
              background: colors[index % colors.length],
            }}
            title={`${segment.asset_class}: ${segment.share.toFixed(1)}%`}
          />
        ))}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
        {segments.map((segment, index) => (
          <li key={segment.asset_class} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-1.5 capitalize text-muted">
              <span
                className="h-2 w-2 rounded-sm"
                style={{ background: colors[index % colors.length] }}
              />
              {segment.asset_class}
            </span>
            <span className="tabular text-slate-200">{segment.share.toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
export function MetricChart({
  data,
  label,
  format = (value: number) => number(value),
  height = 200,
}: {
  data: SeriesPoint[];
  label: string;
  format?: (value: number) => string;
  height?: number;
}) {
  if (data.length < 2) return <NoData hint="Not enough readings yet." />;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={shortDate}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          minTickGap={40}
        />
        <YAxis
          tickFormatter={(value: number) => format(value)}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={56}
          // "auto" lets Recharts pick round tick values; pinning the domain to
          // the raw data min/max produces ticks like 3,377 / 6,377 / 9,377.
          domain={["auto", "auto"]}
          tickCount={5}
        />
        <Tooltip
          cursor={{ stroke: "var(--text-secondary)", strokeWidth: 1, strokeDasharray: "3 3" }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as SeriesPoint;
            return (
              <TooltipShell label={shortDate(point.date)}>
                <Row color="var(--series-3)" name={label} value={format(point.value)} />
              </TooltipShell>
            );
          }}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke="var(--series-3)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
export function PayoffChart({
  schedule,
  height = 200,
}: {
  schedule: { month: number; remaining_balance: number }[];
  height?: number;
}) {
  if (schedule.length < 2) return <NoData hint="Add APR and minimum payments to model a payoff." />;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={schedule} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="payoff-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--series-2)" stopOpacity={0.3} />
            <stop offset="100%" stopColor="var(--series-2)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="month"
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          tickFormatter={(value: number) => `${value}mo`}
          minTickGap={28}
        />
        <YAxis
          tickFormatter={moneyShort}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={56}
        />
        <Tooltip
          cursor={{ stroke: "var(--text-secondary)", strokeWidth: 1, strokeDasharray: "3 3" }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as { month: number; remaining_balance: number };
            return (
              <TooltipShell label={`Month ${point.month}`}>
                <Row
                  color="var(--series-2)"
                  name="Remaining"
                  value={money(point.remaining_balance)}
                />
              </TooltipShell>
            );
          }}
        />
        <Area
          type="monotone"
          dataKey="remaining_balance"
          stroke="var(--series-2)"
          strokeWidth={2}
          fill="url(#payoff-fill)"
          activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
/** Tiny trend line for stat tiles. No axes by design — it shows shape, and the
 *  tile beside it carries the number. */
export function Sparkline({ data, tone = "var(--series-3)" }: { data: SeriesPoint[]; tone?: string }) {
  if (data.length < 2) return null;
  const values = data.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = data
    .map((point, index) => {
      const x = (index / (data.length - 1)) * 100;
      const y = 24 - ((point.value - min) / span) * 22 - 1;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="h-6 w-full" aria-hidden="true">
      <polyline points={points} fill="none" stroke={tone} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Distribution of transaction counts by weekday — used on the Money page. */
export function WeekdayBars({ counts }: { counts: number[] }) {
  const labels = ["S", "M", "T", "W", "T", "F", "S"];
  const max = Math.max(...counts, 1);
  return (
    <div className="flex items-end gap-1.5" style={{ height: 56 }}>
      {counts.map((count, index) => (
        <div key={index} className="flex flex-1 flex-col items-center gap-1">
          <div
            className="w-full rounded-t bg-series-1/70"
            style={{ height: `${Math.max((count / max) * 40, 2)}px` }}
            title={`${labels[index]}: ${count}`}
          />
          <span className="text-[10px] text-ink-500">{labels[index]}</span>
        </div>
      ))}
    </div>
  );
}

function NoData({ hint }: { hint: string }) {
  return (
    <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-ink-700 px-4 text-center text-xs text-muted">
      {hint}
    </div>
  );
}

export { Cell };
