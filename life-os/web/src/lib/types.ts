/** Shapes returned by the API. Kept hand-written and small — only what the UI reads. */

export type Account = {
  id: string;
  name: string;
  institution: string;
  type: string;
  subtype: string;
  mask: string;
  current_balance: number;
  available_balance: number | null;
  credit_limit: number | null;
  include_in_net_worth: boolean;
  is_active: boolean;
  connection_id: string | null;
  last_synced_at: string | null;
  signed_balance: number;
  is_liability: boolean;
  debt: DebtDetail | null;
};

export type DebtDetail = {
  apr: number | null;
  minimum_payment: number | null;
  statement_balance: number | null;
  next_payment_due: string | null;
  original_principal: number | null;
  term_months: number | null;
  notes: string;
};

export type Transaction = {
  id: string;
  account_id: string;
  posted_on: string;
  amount: number;
  description: string;
  merchant: string;
  category: string;
  pending: boolean;
  is_transfer: boolean;
};

export type Holding = {
  id: string;
  account_id: string;
  symbol: string;
  name: string;
  asset_class: string;
  quantity: number;
  price: number;
  market_value: number;
  cost_basis: number | null;
};

export type Bill = {
  id: string;
  name: string;
  merchant: string;
  amount: number;
  cadence: string;
  category: string;
  next_due_on: string | null;
  last_paid_on: string | null;
  is_subscription: boolean;
  autopay: boolean;
  is_active: boolean;
  auto_detected: boolean;
  confidence: number | null;
  dismissed: boolean;
  url: string;
  notes: string;
  monthly_cost: number;
};

export type UpcomingBill = {
  id: string;
  name: string;
  amount: number;
  cadence: string;
  next_due_on: string | null;
  days_until_due: number | null;
  is_subscription: boolean;
  autopay: boolean;
  overdue: boolean;
};

export type Task = {
  id: string;
  title: string;
  notes: string;
  area: string;
  status: string;
  priority: number;
  project_id: string | null;
  due_at: string | null;
  completed_at: string | null;
  estimate_minutes: number | null;
  tags: string[];
  source: string;
  url: string;
};

export type Project = {
  id: string;
  name: string;
  area: string;
  color: string;
  is_archived: boolean;
};

export type Insight = {
  id: string;
  kind: string;
  severity: "info" | "warning" | "critical";
  title: string;
  body: string;
  action_label: string;
  action_href: string;
  data: Record<string, unknown>;
  created_at: string;
};

export type HealthMetricSummary = {
  metric: string;
  label: string;
  value: number;
  unit: string;
  recorded_on: string;
  avg_7d: number | null;
  avg_prev_7d: number | null;
  change_pct: number | null;
  direction: "up" | "down" | "flat";
  higher_is_better: boolean;
};

export type ConnectorField = {
  key: string;
  label: string;
  type: string;
  required: boolean;
  secret: boolean;
  help: string;
  default: unknown;
  options: string[];
};

export type Connector = {
  slug: string;
  name: string;
  category: string;
  mode: "pull" | "push" | "both";
  description: string;
  provides: string[];
  docs_url: string;
  schedulable: boolean;
  fields: ConnectorField[];
};

export type Connection = {
  id: string;
  connector_slug: string;
  display_name: string;
  status: string;
  is_enabled: boolean;
  config: Record<string, unknown>;
  sync_interval_minutes: number;
  last_sync_at: string | null;
  last_error: string | null;
  has_secrets: boolean;
  connector: Connector | null;
};

export type SyncRun = {
  id: string;
  connection_id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  created_count: number;
  updated_count: number;
  message: string;
  trigger: string;
};

export type SeriesPoint = { date: string; value: number };

export type NetWorthPoint = {
  date: string;
  assets: number;
  liabilities: number;
  net_worth: number;
};

export type CashFlowPoint = { month: string; income: number; spending: number; net: number };

export type SpendingSlice = { category: string; amount: number; share: number };

export type PayoffPlan = {
  strategy: string;
  months: number;
  total_interest: number;
  total_paid: number;
  monthly_payment: number;
  payoff_date: string | null;
  feasible: boolean;
  note: string;
  order: {
    account_id: string;
    name: string;
    apr: number;
    minimum: number;
    paid_off_month: number | null;
    interest_paid: number;
  }[];
  schedule: { month: number; remaining_balance: number; interest_paid: number }[];
};

export type Dashboard = {
  generated_at: string;
  user: { display_name: string; email: string };
  finance: {
    assets: number;
    liabilities: number;
    net_worth: number;
    by_type: Record<string, number>;
    account_count: number;
    cash_on_hand: number;
    net_worth_history: NetWorthPoint[];
    cash_flow: CashFlowPoint[];
    spending_30d: SpendingSlice[];
  };
  investments: {
    total_value: number;
    by_class: { asset_class: string; value: number; share: number }[];
    top_holdings: (Holding & { gain_loss: number | null })[];
  };
  debt: {
    total: number;
    count: number;
    months_to_payoff: number;
    payoff_date: string | null;
    total_interest: number;
    monthly_minimum: number;
    feasible: boolean;
  };
  bills: {
    bills_monthly: number;
    subscriptions_monthly: number;
    subscriptions_annual: number;
    total_monthly: number;
    subscription_count: number;
    bill_count: number;
    upcoming: UpcomingBill[];
  };
  tasks: { open: number; overdue: number; today: Task[] };
  health: { metrics: HealthMetricSummary[] };
  insights: Insight[];
  system: { last_sync_at: string | null; connection_count: number };
};
