import { Link } from "react-router-dom";

import { CashFlowChart, NetWorthChart, SpendingBars } from "../components/charts";
import { PageHeader } from "../components/Layout";
import { Badge, Button, Card, ErrorNote, Spinner, StatTile } from "../components/ui";
import { money, metricValue, relativeDays, shortDate } from "../lib/format";
import { post } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { Dashboard as DashboardData } from "../lib/types";
import { useState } from "react";

export default function Dashboard() {
  const { data, error, loading, reload } = useApi<DashboardData>("/dashboard?refresh=true");
  const [syncing, setSyncing] = useState(false);

  async function syncAll() {
    setSyncing(true);
    try {
      await post("/connections/sync-all");
      reload();
    } finally {
      setSyncing(false);
    }
  }

  if (loading && !data) return <Spinner label="Loading your dashboard" />;
  if (error) return <ErrorNote message={error} onRetry={reload} />;
  if (!data) return null;

  const { finance, investments, debt, bills, tasks, health, insights, system } = data;
  const netWorthTone = finance.net_worth >= 0 ? "neutral" : "critical";

  return (
    <>
      <PageHeader
        title={`Good to see you, ${data.user.display_name || "Rob"}`}
        subtitle={
          system.last_sync_at
            ? `Last sync ${new Date(system.last_sync_at).toLocaleString()}`
            : "No connections have synced yet."
        }
        action={
          <Button onClick={syncAll} disabled={syncing} variant="primary">
            {syncing ? "Syncing…" : "Sync everything"}
          </Button>
        }
      />

      {insights.length > 0 && (
        <div className="mb-6 space-y-2">
          {insights.slice(0, 4).map((insight) => (
            <div
              key={insight.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-ink-700 bg-ink-800 px-4 py-3"
            >
              <div className="flex min-w-0 items-center gap-3">
                <Badge
                  tone={
                    insight.severity === "critical"
                      ? "critical"
                      : insight.severity === "warning"
                        ? "warning"
                        : "neutral"
                  }
                >
                  {insight.severity}
                </Badge>
                <div className="min-w-0">
                  <p className="truncate text-sm text-slate-100">{insight.title}</p>
                  <p className="truncate text-xs text-muted">{insight.body}</p>
                </div>
              </div>
              {insight.action_href && (
                <Link
                  to={insight.action_href.split("?")[0]}
                  className="shrink-0 text-xs font-medium text-series-1 hover:underline"
                >
                  {insight.action_label} →
                </Link>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Net worth"
          value={money(finance.net_worth)}
          tone={netWorthTone}
          hint={`${money(finance.assets)} assets · ${money(finance.liabilities)} owed`}
        />
        <StatTile
          label="Cash on hand"
          value={money(finance.cash_on_hand)}
          hint={`${money(bills.total_monthly)}/mo in obligations`}
        />
        <StatTile
          label="Total debt"
          value={money(debt.total)}
          tone={debt.total > 0 ? "warning" : "good"}
          hint={
            debt.feasible && debt.payoff_date
              ? `Clear by ${debt.payoff_date} at minimums`
              : "Add APRs to model a payoff"
          }
        />
        <StatTile
          label="Investments"
          value={money(investments.total_value)}
          hint={`${investments.top_holdings.length} positions tracked`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Net worth" subtitle="Last 180 days" className="lg:col-span-2">
          <NetWorthChart data={finance.net_worth_history} />
        </Card>

        <Card title="Coming due" subtitle="Next 14 days">
          {bills.upcoming.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted">Nothing due. Enjoy it.</p>
          ) : (
            <ul className="space-y-2.5">
              {bills.upcoming.slice(0, 7).map((bill) => (
                <li key={bill.id} className="flex items-center justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <p className="truncate text-slate-200">{bill.name}</p>
                    <p className="text-xs text-muted">
                      {relativeDays(bill.days_until_due)}
                      {bill.autopay && " · autopay"}
                    </p>
                  </div>
                  <span
                    className={`tabular shrink-0 text-sm ${
                      bill.overdue ? "text-status-critical" : "text-slate-200"
                    }`}
                  >
                    {money(bill.amount, true)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Cash flow" subtitle="Income vs spending by month" className="lg:col-span-2">
          <CashFlowChart data={finance.cash_flow} />
        </Card>

        <Card title="Where it went" subtitle="Last 30 days">
          <SpendingBars data={finance.spending_30d} />
        </Card>

        <Card
          title="Today"
          subtitle={`${tasks.open} open · ${tasks.overdue} overdue`}
          action={
            <Link to="/tasks" className="text-xs text-series-1 hover:underline">
              All tasks →
            </Link>
          }
        >
          {tasks.today.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted">Nothing scheduled for today.</p>
          ) : (
            <ul className="space-y-2">
              {tasks.today.map((task) => (
                <li key={task.id} className="flex items-center gap-2.5 text-sm">
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      task.priority === 1 ? "bg-status-critical" : "bg-series-1"
                    }`}
                  />
                  <span className="min-w-0 flex-1 truncate text-slate-200">{task.title}</span>
                  <span className="shrink-0 text-xs text-muted">
                    {task.due_at ? shortDate(task.due_at) : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Health"
          subtitle="7-day trend"
          action={
            <Link to="/health" className="text-xs text-series-1 hover:underline">
              Details →
            </Link>
          }
        >
          {health.metrics.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted">
              Connect Apple Health to see your numbers.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {health.metrics.map((metric) => (
                <li key={metric.metric} className="flex items-center justify-between text-sm">
                  <span className="text-muted">{metric.label}</span>
                  <span className="flex items-center gap-2">
                    <span className="tabular text-slate-100">
                      {metricValue(metric.metric, metric.value, metric.unit)}
                    </span>
                    {metric.change_pct !== null && metric.direction !== "flat" && (
                      <span
                        className={`text-[11px] ${
                          metric.direction === "up" ? "text-status-good" : "text-status-warning"
                        }`}
                      >
                        {metric.change_pct > 0 ? "+" : ""}
                        {metric.change_pct.toFixed(0)}%
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Subscriptions" subtitle={`${bills.subscription_count} tracked`}>
          <p className="tabular text-2xl font-semibold text-slate-100">
            {money(bills.subscriptions_monthly, true)}
            <span className="ml-1 text-sm font-normal text-muted">/mo</span>
          </p>
          <p className="mt-1 text-xs text-muted">
            {money(bills.subscriptions_annual)} a year across every recurring charge found.
          </p>
          <Link
            to="/bills"
            className="mt-4 inline-block text-xs font-medium text-series-1 hover:underline"
          >
            Review subscriptions →
          </Link>
        </Card>
      </div>
    </>
  );
}
