import { useState } from "react";

import { PageHeader } from "../components/Layout";
import { Badge, Button, Card, ErrorNote, Field, Spinner, StatTile, inputClass } from "../components/ui";
import { money, relativeDays, shortDate, titleize } from "../lib/format";
import { del, patch, post } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { Bill } from "../lib/types";

const CADENCES = ["weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual", "one_time"];

type Summary = {
  bills_monthly: number;
  subscriptions_monthly: number;
  subscriptions_annual: number;
  total_monthly: number;
  subscription_count: number;
  bill_count: number;
};

export default function Bills() {
  const bills = useApi<Bill[]>("/bills");
  const summary = useApi<Summary>("/bills/summary");
  const [filter, setFilter] = useState<"all" | "subscriptions" | "bills">("all");
  const [adding, setAdding] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [detectResult, setDetectResult] = useState<string | null>(null);

  function refresh() {
    bills.reload();
    summary.reload();
  }

  async function detect() {
    setDetecting(true);
    setDetectResult(null);
    try {
      const result = await post<{ detected: number; results: { status: string }[] }>("/bills/detect");
      const created = result.results.filter((row) => row.status === "created").length;
      setDetectResult(
        created > 0
          ? `Found ${created} new recurring charge${created === 1 ? "" : "s"}.`
          : `Scanned ${result.detected} recurring series — nothing new.`,
      );
      refresh();
    } catch (cause) {
      setDetectResult((cause as Error).message);
    } finally {
      setDetecting(false);
    }
  }

  const visible = (bills.data ?? []).filter((bill) => {
    if (filter === "subscriptions") return bill.is_subscription;
    if (filter === "bills") return !bill.is_subscription;
    return true;
  });

  const sorted = [...visible].sort((a, b) => {
    if (!a.next_due_on) return 1;
    if (!b.next_due_on) return -1;
    return a.next_due_on.localeCompare(b.next_due_on);
  });

  async function markPaid(bill: Bill) {
    await post(`/bills/${bill.id}/paid`, {});
    refresh();
  }

  async function toggleSubscription(bill: Bill) {
    await patch(`/bills/${bill.id}`, { is_subscription: !bill.is_subscription });
    refresh();
  }

  async function dismiss(bill: Bill) {
    // Detected-but-wrong entries get dismissed so the detector stops re-adding
    // them; hand-made ones are simply deleted.
    if (bill.auto_detected) await patch(`/bills/${bill.id}`, { dismissed: true });
    else await del(`/bills/${bill.id}`);
    refresh();
  }

  return (
    <>
      <PageHeader
        title="Bills & subscriptions"
        subtitle="Everything with a due date, plus every recurring charge found in your transactions."
        action={
          <div className="flex gap-2">
            <Button onClick={detect} disabled={detecting}>
              {detecting ? "Scanning…" : "Detect recurring"}
            </Button>
            <Button variant="primary" onClick={() => setAdding((value) => !value)}>
              {adding ? "Cancel" : "Add bill"}
            </Button>
          </div>
        }
      />

      {detectResult && (
        <p className="mb-4 rounded-lg border border-ink-700 bg-ink-800 px-4 py-2.5 text-xs text-muted">
          {detectResult}
        </p>
      )}

      {adding && <AddBillForm onDone={() => { setAdding(false); refresh(); }} />}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Monthly obligations"
          value={money(summary.data?.total_monthly ?? 0, true)}
          hint="every bill and subscription, normalised"
        />
        <StatTile
          label="Subscriptions"
          value={money(summary.data?.subscriptions_monthly ?? 0, true)}
          tone="warning"
          hint={`${summary.data?.subscription_count ?? 0} services`}
        />
        <StatTile
          label="Annual subscription cost"
          value={money(summary.data?.subscriptions_annual ?? 0)}
          hint="what cancelling everything would save"
        />
        <StatTile
          label="Fixed bills"
          value={money(summary.data?.bills_monthly ?? 0, true)}
          hint="rent, utilities, insurance"
        />
      </div>

      <Card
        title="All recurring charges"
        action={
          <div className="flex gap-1">
            {(["all", "subscriptions", "bills"] as const).map((option) => (
              <button
                key={option}
                onClick={() => setFilter(option)}
                className={`rounded-md px-2.5 py-1 text-xs capitalize transition-colors ${
                  filter === option ? "bg-series-1/15 text-series-1" : "text-muted hover:text-slate-200"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        }
      >
        {bills.loading && <Spinner />}
        {bills.error && <ErrorNote message={bills.error} onRetry={bills.reload} />}
        {!bills.loading && sorted.length === 0 && (
          <p className="py-8 text-center text-xs text-muted">
            Nothing here yet. Import transactions, then hit "Detect recurring".
          </p>
        )}

        {sorted.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-700 text-left text-[11px] uppercase tracking-wider text-muted">
                  <th className="pb-2 font-medium">Name</th>
                  <th className="pb-2 font-medium">Cadence</th>
                  <th className="pb-2 font-medium">Next due</th>
                  <th className="pb-2 text-right font-medium">Amount</th>
                  <th className="pb-2 text-right font-medium">Per month</th>
                  <th className="pb-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-750">
                {sorted.map((bill) => {
                  const days = bill.next_due_on
                    ? Math.round(
                        (new Date(`${bill.next_due_on}T12:00:00`).getTime() - Date.now()) / 86_400_000,
                      )
                    : null;
                  return (
                    <tr key={bill.id} className="hover:bg-ink-750/50">
                      <td className="py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-200">{bill.name}</span>
                          {bill.is_subscription && <Badge tone="accent">sub</Badge>}
                          {bill.autopay && <Badge tone="good">autopay</Badge>}
                          {bill.auto_detected && (
                            <Badge>
                              detected{bill.confidence ? ` ${Math.round(bill.confidence * 100)}%` : ""}
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 text-xs capitalize text-muted">
                        {bill.cadence.replace("_", " ")}
                      </td>
                      <td className="py-2.5 text-xs">
                        {bill.next_due_on ? (
                          <span className={days !== null && days < 0 ? "text-status-critical" : "text-muted"}>
                            {shortDate(bill.next_due_on)}
                            <span className="ml-1.5 opacity-70">({relativeDays(days)})</span>
                          </span>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                      <td className="tabular py-2.5 text-right text-slate-100">
                        {money(bill.amount, true)}
                      </td>
                      <td className="tabular py-2.5 text-right text-muted">
                        {money(bill.monthly_cost, true)}
                      </td>
                      <td className="py-2.5">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" onClick={() => markPaid(bill)}>
                            Paid
                          </Button>
                          <Button variant="ghost" onClick={() => toggleSubscription(bill)}>
                            {bill.is_subscription ? "Not a sub" : "Mark sub"}
                          </Button>
                          <Button variant="ghost" onClick={() => dismiss(bill)}>
                            {bill.auto_detected ? "Dismiss" : "Delete"}
                          </Button>
                        </div>
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

function AddBillForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [cadence, setCadence] = useState("monthly");
  const [dueOn, setDueOn] = useState("");
  const [isSubscription, setIsSubscription] = useState(false);
  const [autopay, setAutopay] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await post("/bills", {
        name,
        amount: Number(amount) || 0,
        cadence,
        next_due_on: dueOn || null,
        is_subscription: isSubscription,
        autopay,
      });
      onDone();
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  return (
    <Card title="New bill" className="mb-6">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-4">
        <Field label="Name">
          <input required className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Amount">
          <input
            required
            type="number"
            step="0.01"
            className={inputClass}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
        <Field label="Cadence">
          <select className={inputClass} value={cadence} onChange={(e) => setCadence(e.target.value)}>
            {CADENCES.map((option) => (
              <option key={option} value={option}>
                {titleize(option)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Next due">
          <input type="date" className={inputClass} value={dueOn} onChange={(e) => setDueOn(e.target.value)} />
        </Field>
        <div className="col-span-full flex items-center gap-5 text-xs text-muted">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="accent-series-1"
              checked={isSubscription}
              onChange={(e) => setIsSubscription(e.target.checked)}
            />
            This is a subscription I could cancel
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="accent-series-1"
              checked={autopay}
              onChange={(e) => setAutopay(e.target.checked)}
            />
            On autopay
          </label>
        </div>
        {error && <p className="col-span-full text-xs text-status-critical">{error}</p>}
        <div className="col-span-full">
          <Button type="submit" variant="primary">
            Add bill
          </Button>
        </div>
      </form>
    </Card>
  );
}
