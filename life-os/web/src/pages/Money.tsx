import { useMemo, useState } from "react";

import { CashFlowChart, SpendingBars, WeekdayBars } from "../components/charts";
import { PageHeader } from "../components/Layout";
import { Badge, Button, Card, ErrorNote, Field, Spinner, StatTile, inputClass } from "../components/ui";
import { money, shortDate, titleize } from "../lib/format";
import { patch, post } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { Account, CashFlowPoint, SpendingSlice, Transaction } from "../lib/types";

const ACCOUNT_TYPES = ["depository", "credit", "loan", "investment", "property", "other"];

export default function Money() {
  const accounts = useApi<Account[]>("/accounts");
  const cashFlow = useApi<CashFlowPoint[]>("/finance/cash-flow?months=6");
  const spending = useApi<SpendingSlice[]>("/finance/spending?days=30");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const query = `/transactions?limit=150${category ? `&category=${encodeURIComponent(category)}` : ""}${
    search ? `&search=${encodeURIComponent(search)}` : ""
  }`;
  const transactions = useApi<Transaction[]>(query, [category, search]);
  const categories = useApi<string[]>("/categories");
  const [adding, setAdding] = useState(false);

  const accountName = useMemo(() => {
    const map = new Map((accounts.data ?? []).map((account) => [account.id, account.name]));
    return (id: string) => map.get(id) ?? "—";
  }, [accounts.data]);

  const weekdayCounts = useMemo(() => {
    const counts = [0, 0, 0, 0, 0, 0, 0];
    for (const txn of transactions.data ?? []) {
      if (txn.amount >= 0) continue;
      counts[new Date(`${txn.posted_on}T12:00:00`).getDay()] += 1;
    }
    return counts;
  }, [transactions.data]);

  const assets = (accounts.data ?? []).filter((account) => !account.is_liability);
  const liabilities = (accounts.data ?? []).filter((account) => account.is_liability);
  const totalAssets = assets.reduce((sum, account) => sum + account.signed_balance, 0);
  const totalDebt = liabilities.reduce((sum, account) => sum + Math.abs(account.signed_balance), 0);

  async function reclassify(transaction: Transaction, nextCategory: string) {
    await patch(`/transactions/${transaction.id}`, { category: nextCategory });
    transactions.reload();
    spending.reload();
    categories.reload();
  }

  return (
    <>
      <PageHeader
        title="Money"
        subtitle="Accounts, cash flow and every transaction Life OS knows about."
        action={<Button onClick={() => setAdding((value) => !value)}>{adding ? "Cancel" : "Add account"}</Button>}
      />

      {adding && (
        <AddAccountForm
          onDone={() => {
            setAdding(false);
            accounts.reload();
          }}
        />
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <StatTile label="Assets" value={money(totalAssets)} hint={`${assets.length} accounts`} />
        <StatTile
          label="Liabilities"
          value={money(totalDebt)}
          tone={totalDebt > 0 ? "warning" : "good"}
          hint={`${liabilities.length} accounts`}
        />
        <StatTile label="Net" value={money(totalAssets - totalDebt)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Cash flow" subtitle="Last 6 months" className="lg:col-span-2">
          {cashFlow.loading ? <Spinner /> : <CashFlowChart data={cashFlow.data ?? []} />}
        </Card>

        <Card title="Spending" subtitle="Last 30 days by category">
          {spending.loading ? <Spinner /> : <SpendingBars data={(spending.data ?? []).slice(0, 8)} />}
        </Card>

        <Card title="Accounts" className="lg:col-span-2">
          {accounts.loading && <Spinner />}
          {accounts.error && <ErrorNote message={accounts.error} onRetry={accounts.reload} />}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-700 text-left text-[11px] uppercase tracking-wider text-muted">
                  <th className="pb-2 font-medium">Account</th>
                  <th className="pb-2 font-medium">Type</th>
                  <th className="pb-2 text-right font-medium">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-750">
                {(accounts.data ?? []).map((account) => (
                  <tr key={account.id}>
                    <td className="py-2.5">
                      <p className="text-slate-200">{account.name}</p>
                      <p className="text-xs text-muted">
                        {account.institution || "—"}
                        {account.mask && ` ····${account.mask}`}
                      </p>
                    </td>
                    <td className="py-2.5">
                      <Badge tone={account.is_liability ? "warning" : "neutral"}>
                        {account.type}
                      </Badge>
                    </td>
                    <td
                      className={`tabular py-2.5 text-right ${
                        account.is_liability ? "text-status-warning" : "text-slate-100"
                      }`}
                    >
                      {money(account.signed_balance, true)}
                      {account.credit_limit ? (
                        <span className="block text-[11px] text-muted">
                          of {money(account.credit_limit)} limit
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Spending rhythm" subtitle="Purchases by weekday">
          <WeekdayBars counts={weekdayCounts} />
          <p className="mt-3 text-xs text-muted">
            Based on the {(transactions.data ?? []).length} transactions currently in view.
          </p>
        </Card>
      </div>

      <Card
        title="Transactions"
        className="mt-4"
        action={
          <div className="flex gap-2">
            <input
              placeholder="Search…"
              className="w-36 rounded-lg border border-ink-600 bg-ink-850 px-2.5 py-1 text-xs text-slate-100 focus:border-series-1 focus:outline-none"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <select
              className="rounded-lg border border-ink-600 bg-ink-850 px-2.5 py-1 text-xs text-slate-100 focus:border-series-1 focus:outline-none"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            >
              <option value="">All categories</option>
              {(categories.data ?? []).map((name) => (
                <option key={name} value={name}>
                  {titleize(name)}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {transactions.loading && <Spinner />}
        {transactions.error && <ErrorNote message={transactions.error} />}
        {!transactions.loading && (transactions.data ?? []).length === 0 && (
          <p className="py-8 text-center text-xs text-muted">
            No transactions match. Import a CSV from the Connections page to get started.
          </p>
        )}
        {(transactions.data ?? []).length > 0 && (
          <div className="max-h-[32rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-ink-800">
                <tr className="border-b border-ink-700 text-left text-[11px] uppercase tracking-wider text-muted">
                  <th className="pb-2 font-medium">Date</th>
                  <th className="pb-2 font-medium">Description</th>
                  <th className="pb-2 font-medium">Account</th>
                  <th className="pb-2 font-medium">Category</th>
                  <th className="pb-2 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-750">
                {(transactions.data ?? []).map((txn) => (
                  <tr key={txn.id} className="hover:bg-ink-750/50">
                    <td className="tabular whitespace-nowrap py-2 text-xs text-muted">
                      {shortDate(txn.posted_on)}
                    </td>
                    <td className="max-w-xs truncate py-2 text-slate-200" title={txn.description}>
                      {txn.description}
                      {txn.is_transfer && (
                        <span className="ml-2">
                          <Badge>transfer</Badge>
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-xs text-muted">{accountName(txn.account_id)}</td>
                    <td className="py-2">
                      <select
                        value={txn.category}
                        onChange={(event) => reclassify(txn, event.target.value)}
                        className="rounded border border-transparent bg-transparent py-0.5 text-xs text-muted hover:border-ink-600 focus:border-series-1 focus:outline-none"
                      >
                        {[...new Set([txn.category, ...(categories.data ?? [])])].map((name) => (
                          <option key={name} value={name}>
                            {titleize(name)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td
                      className={`tabular whitespace-nowrap py-2 text-right ${
                        txn.amount >= 0 ? "text-status-good" : "text-slate-200"
                      }`}
                    >
                      {money(txn.amount, true)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function AddAccountForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [institution, setInstitution] = useState("");
  const [type, setType] = useState("depository");
  const [balance, setBalance] = useState("0");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await post("/accounts", {
        name,
        institution,
        type,
        current_balance: Number(balance) || 0,
      });
      onDone();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  return (
    <Card title="New account" subtitle="For anything without an API — property, cash, a 401k portal." className="mb-6">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-4">
        <Field label="Name">
          <input required className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Institution">
          <input className={inputClass} value={institution} onChange={(e) => setInstitution(e.target.value)} />
        </Field>
        <Field label="Type">
          <select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
            {ACCOUNT_TYPES.map((option) => (
              <option key={option} value={option}>
                {titleize(option)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Balance" help="For cards and loans, enter what you owe as a positive number.">
          <input
            type="number"
            step="0.01"
            className={inputClass}
            value={balance}
            onChange={(e) => setBalance(e.target.value)}
          />
        </Field>
        {error && <p className="col-span-full text-xs text-status-critical">{error}</p>}
        <div className="col-span-full">
          <Button type="submit" variant="primary">
            Create account
          </Button>
        </div>
      </form>
    </Card>
  );
}
