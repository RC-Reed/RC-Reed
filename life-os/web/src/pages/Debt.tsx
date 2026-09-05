import { useEffect, useState } from "react";

import { PayoffChart } from "../components/charts";
import { PageHeader } from "../components/Layout";
import { Badge, Button, Card, ErrorNote, Field, Spinner, StatTile, inputClass } from "../components/ui";
import { money, percent } from "../lib/format";
import { post, put } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { Account, PayoffPlan } from "../lib/types";

type PlanResponse = {
  plan: PayoffPlan;
  comparison: {
    total_debt: number;
    debt_count: number;
    avalanche: PayoffPlan;
    snowball: PayoffPlan;
    interest_saved_with_avalanche: number;
  };
};

export default function Debt() {
  const accounts = useApi<Account[]>("/accounts");
  const [extra, setExtra] = useState(0);
  const [strategy, setStrategy] = useState<"avalanche" | "snowball">("avalanche");
  const [result, setResult] = useState<PlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    post<PlanResponse>("/finance/payoff-plan", { extra_payment: extra, strategy })
      .then((payload) => !cancelled && setResult(payload))
      .catch((cause: Error) => !cancelled && setError(cause.message))
      .finally(() => !cancelled && setBusy(false));
    return () => {
      cancelled = true;
    };
  }, [extra, strategy, accounts.data]);

  const debts = (accounts.data ?? []).filter((account) => account.is_liability);
  const plan = result?.plan;
  const comparison = result?.comparison;

  return (
    <>
      <PageHeader
        title="Debt"
        subtitle="What you owe, what it costs, and the fastest way out."
      />

      {debts.length === 0 && !accounts.loading && (
        <Card>
          <p className="py-6 text-center text-sm text-muted">
            No credit or loan accounts yet. Add one on the Money page, or connect an institution.
          </p>
        </Card>
      )}

      {debts.length > 0 && (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Total owed"
              value={money(comparison?.total_debt ?? 0)}
              tone="warning"
              hint={`${debts.length} accounts`}
            />
            <StatTile
              label="Monthly payment"
              value={money(plan?.monthly_payment ?? 0)}
              hint={extra > 0 ? `includes ${money(extra)} extra` : "minimums only"}
            />
            <StatTile
              label="Debt free"
              value={plan?.payoff_date ?? "—"}
              tone={plan?.feasible ? "good" : "critical"}
              hint={plan ? `${plan.months} months` : undefined}
            />
            <StatTile
              label="Interest cost"
              value={money(plan?.total_interest ?? 0)}
              tone="warning"
              hint="over the life of the plan"
            />
          </div>

          <Card
            title="Payoff plan"
            subtitle="Move the extra payment to see the effect immediately."
            className="mb-4"
          >
            <div className="mb-5 flex flex-wrap items-end gap-6">
              <div className="min-w-[240px] flex-1">
                <div className="mb-1 flex items-baseline justify-between">
                  <span className="text-xs font-medium text-muted-strong">Extra monthly payment</span>
                  <span className="tabular text-sm font-semibold text-series-1">{money(extra)}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={2000}
                  step={25}
                  value={extra}
                  onChange={(event) => setExtra(Number(event.target.value))}
                  className="w-full accent-series-1"
                  aria-label="Extra monthly payment"
                />
              </div>

              <div className="flex gap-2">
                {(["avalanche", "snowball"] as const).map((option) => (
                  <button
                    key={option}
                    onClick={() => setStrategy(option)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                      strategy === option
                        ? "border-series-1 bg-series-1/15 text-series-1"
                        : "border-ink-600 text-muted hover:text-slate-200"
                    }`}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>

            {error && <ErrorNote message={error} />}
            {busy && !plan && <Spinner label="Modelling" />}

            {plan && !plan.feasible && (
              <div className="mb-4 rounded-lg border border-status-critical/40 bg-status-critical/10 px-4 py-3 text-xs text-status-critical">
                {plan.note}
              </div>
            )}

            {plan && <PayoffChart schedule={plan.schedule} />}

            {comparison && comparison.interest_saved_with_avalanche !== 0 && (
              <p className="mt-4 rounded-lg border border-ink-700 bg-ink-850 px-4 py-3 text-xs text-muted">
                {comparison.interest_saved_with_avalanche > 0 ? (
                  <>
                    <span className="font-medium text-slate-200">Avalanche</span> saves{" "}
                    <span className="tabular font-medium text-status-good">
                      {money(comparison.interest_saved_with_avalanche)}
                    </span>{" "}
                    in interest versus snowball — {comparison.avalanche.months} months against{" "}
                    {comparison.snowball.months}. Snowball clears individual accounts sooner, which
                    some people find easier to stick with.
                  </>
                ) : (
                  <>
                    Both strategies cost the same here — your highest-rate debt also happens to be
                    your smallest, so they target the same account first.
                  </>
                )}
              </p>
            )}
          </Card>

          <Card
            title="Payoff order"
            subtitle={
              extra > 0
                ? `The order debts clear under the ${strategy} method.`
                : `The order debts clear. With no extra payment there is no surplus to direct, so ${strategy} only takes effect as each account frees up its minimum.`
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ink-700 text-left text-[11px] uppercase tracking-wider text-muted">
                    <th className="pb-2 font-medium">Clears</th>
                    <th className="pb-2 font-medium">Account</th>
                    <th className="pb-2 text-right font-medium">Balance</th>
                    <th className="pb-2 text-right font-medium">APR</th>
                    <th className="pb-2 text-right font-medium">Minimum</th>
                    <th className="pb-2 text-right font-medium">Cleared</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-750">
                  {(plan?.order ?? []).map((line, index) => {
                    const account = debts.find((item) => item.id === line.account_id);
                    return (
                      <tr key={line.account_id}>
                        <td className="py-2.5 text-xs text-muted">{index + 1}</td>
                        <td className="py-2.5 text-slate-200">{line.name}</td>
                        <td className="tabular py-2.5 text-right text-slate-200">
                          {money(Math.abs(account?.signed_balance ?? 0), true)}
                        </td>
                        <td className="tabular py-2.5 text-right">
                          <span className={line.apr >= 15 ? "text-status-critical" : "text-muted"}>
                            {percent(line.apr, 2)}
                          </span>
                        </td>
                        <td className="tabular py-2.5 text-right text-muted">
                          {money(line.minimum, true)}
                        </td>
                        <td className="tabular py-2.5 text-right text-muted">
                          {line.paid_off_month ? `month ${line.paid_off_month}` : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {debts.map((account) => (
              <DebtTermsCard key={account.id} account={account} onSaved={accounts.reload} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function DebtTermsCard({ account, onSaved }: { account: Account; onSaved: () => void }) {
  const [apr, setApr] = useState(account.debt?.apr?.toString() ?? "");
  const [minimum, setMinimum] = useState(account.debt?.minimum_payment?.toString() ?? "");
  const [due, setDue] = useState(account.debt?.next_payment_due ?? "");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await put(`/accounts/${account.id}/debt`, {
        apr: apr === "" ? null : Number(apr),
        minimum_payment: minimum === "" ? null : Number(minimum),
        next_payment_due: due || null,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      onSaved();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  const missing = !account.debt?.apr || !account.debt?.minimum_payment;

  return (
    <Card
      title={account.name}
      subtitle={`${money(Math.abs(account.signed_balance), true)} owed`}
      action={missing ? <Badge tone="warning">terms missing</Badge> : undefined}
    >
      <form onSubmit={save} className="grid grid-cols-3 gap-3">
        <Field label="APR %">
          <input
            type="number"
            step="0.01"
            className={inputClass}
            value={apr}
            onChange={(event) => setApr(event.target.value)}
          />
        </Field>
        <Field label="Minimum">
          <input
            type="number"
            step="0.01"
            className={inputClass}
            value={minimum}
            onChange={(event) => setMinimum(event.target.value)}
          />
        </Field>
        <Field label="Next due">
          <input
            type="date"
            className={inputClass}
            value={due}
            onChange={(event) => setDue(event.target.value)}
          />
        </Field>
        {error && <p className="col-span-3 text-xs text-status-critical">{error}</p>}
        <div className="col-span-3 flex items-center gap-3">
          <Button type="submit">Save terms</Button>
          {saved && <span className="text-xs text-status-good">Saved</span>}
        </div>
      </form>
    </Card>
  );
}
