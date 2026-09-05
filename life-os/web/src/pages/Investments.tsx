import { useMemo } from "react";

import { AllocationBar } from "../components/charts";
import { PageHeader } from "../components/Layout";
import { Badge, Card, ErrorNote, Spinner, StatTile } from "../components/ui";
import { money, percent, quantity } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { Account, Holding } from "../lib/types";

type Allocation = {
  total_value: number;
  by_class: { asset_class: string; value: number; share: number }[];
};

export default function Investments() {
  const holdings = useApi<Holding[]>("/holdings");
  const allocation = useApi<Allocation>("/finance/allocation");
  const accounts = useApi<Account[]>("/accounts");

  const investmentAccounts = (accounts.data ?? []).filter(
    (account) => account.type === "investment",
  );

  const totals = useMemo(() => {
    const rows = holdings.data ?? [];
    const value = rows.reduce((sum, row) => sum + row.market_value, 0);
    const basis = rows.reduce((sum, row) => sum + (row.cost_basis ?? 0), 0);
    const withBasis = rows.filter((row) => row.cost_basis !== null);
    return {
      value,
      basis,
      gain: basis > 0 ? value - basis : null,
      gainPct: basis > 0 ? ((value - basis) / basis) * 100 : null,
      coverage: rows.length ? withBasis.length / rows.length : 0,
    };
  }, [holdings.data]);

  const accountName = useMemo(() => {
    const map = new Map((accounts.data ?? []).map((account) => [account.id, account.name]));
    return (id: string) => map.get(id) ?? "—";
  }, [accounts.data]);

  return (
    <>
      <PageHeader
        title="Investments"
        subtitle="Positions across every brokerage and retirement account."
      />

      {holdings.error && <ErrorNote message={holdings.error} onRetry={holdings.reload} />}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Market value" value={money(totals.value)} hint={`${(holdings.data ?? []).length} positions`} />
        <StatTile label="Cost basis" value={money(totals.basis)} hint={totals.coverage < 1 ? "partial — some positions lack basis" : "complete"} />
        <StatTile
          label="Unrealised gain"
          value={totals.gain === null ? "—" : money(totals.gain)}
          tone={totals.gain === null ? "neutral" : totals.gain >= 0 ? "good" : "critical"}
          hint={totals.gainPct === null ? undefined : percent(totals.gainPct)}
        />
        <StatTile label="Accounts" value={String(investmentAccounts.length)} hint="brokerage, IRA, 401k" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Allocation" subtitle="By asset class">
          {allocation.loading ? <Spinner /> : <AllocationBar data={allocation.data?.by_class ?? []} />}
        </Card>

        <Card title="Accounts" className="lg:col-span-2">
          {investmentAccounts.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted">
              No investment accounts yet. Import a Fidelity positions CSV from the Connections page.
            </p>
          ) : (
            <ul className="divide-y divide-ink-750">
              {investmentAccounts.map((account) => (
                <li key={account.id} className="flex items-center justify-between py-2.5">
                  <div>
                    <p className="text-sm text-slate-200">{account.name}</p>
                    <p className="text-xs text-muted">
                      {account.institution}
                      {account.mask && ` ····${account.mask}`}
                      {account.last_synced_at &&
                        ` · updated ${new Date(account.last_synced_at).toLocaleDateString()}`}
                    </p>
                  </div>
                  <span className="tabular text-sm text-slate-100">
                    {money(account.current_balance, true)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Holdings" className="mt-4">
        {holdings.loading && <Spinner />}
        {!holdings.loading && (holdings.data ?? []).length === 0 ? (
          <p className="py-8 text-center text-xs text-muted">
            No positions yet. Export "Portfolio Positions" from Fidelity and upload it under
            Connections → Fidelity (CSV export).
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-700 text-left text-[11px] uppercase tracking-wider text-muted">
                  <th className="pb-2 font-medium">Symbol</th>
                  <th className="pb-2 font-medium">Account</th>
                  <th className="pb-2 font-medium">Class</th>
                  <th className="pb-2 text-right font-medium">Shares</th>
                  <th className="pb-2 text-right font-medium">Price</th>
                  <th className="pb-2 text-right font-medium">Value</th>
                  <th className="pb-2 text-right font-medium">Gain / loss</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-750">
                {(holdings.data ?? []).map((holding) => {
                  const gain =
                    holding.cost_basis === null ? null : holding.market_value - holding.cost_basis;
                  const gainPct =
                    holding.cost_basis && holding.cost_basis > 0
                      ? (gain! / holding.cost_basis) * 100
                      : null;
                  return (
                    <tr key={holding.id} className="hover:bg-ink-750/50">
                      <td className="py-2.5">
                        <p className="font-medium text-slate-100">{holding.symbol}</p>
                        <p className="max-w-[16rem] truncate text-xs text-muted" title={holding.name}>
                          {holding.name}
                        </p>
                      </td>
                      <td className="py-2.5 text-xs text-muted">{accountName(holding.account_id)}</td>
                      <td className="py-2.5">
                        <Badge>{holding.asset_class}</Badge>
                      </td>
                      <td className="tabular py-2.5 text-right text-muted">
                        {quantity(holding.quantity)}
                      </td>
                      <td className="tabular py-2.5 text-right text-muted">
                        {money(holding.price, true)}
                      </td>
                      <td className="tabular py-2.5 text-right text-slate-100">
                        {money(holding.market_value, true)}
                      </td>
                      <td className="tabular py-2.5 text-right">
                        {gain === null ? (
                          <span className="text-muted">—</span>
                        ) : (
                          <span className={gain >= 0 ? "text-status-good" : "text-status-critical"}>
                            {gain >= 0 ? "+" : ""}
                            {money(gain)}
                            {gainPct !== null && (
                              <span className="ml-1.5 text-[11px] opacity-80">
                                {gainPct >= 0 ? "+" : ""}
                                {gainPct.toFixed(1)}%
                              </span>
                            )}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
