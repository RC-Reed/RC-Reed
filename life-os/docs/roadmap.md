# Roadmap

What's deliberately not built yet, and what it would take. Ordered by how much
each is worth relative to its cost.

## Next

**Alembic migrations.** `create_all()` is additive-only, which is fine while the
schema moves and there's one operator. The moment you have data you'd be upset
to lose, this becomes the top item. See `architecture.md § Schema changes` —
it's about an hour of work and the models are already written in the style
Alembic autogenerates cleanly from.

**Budgets.** Per-category monthly targets with progress against actuals. The
data is all there (categorised transactions, `spending_by_category`); it needs a
`budgets` table, a service, and a page. The insight rule writes itself:
"groceries is at 90% with 11 days left".

**Notifications.** The insight engine already produces exactly the things worth
pushing. A notifier interface plus one implementation (ntfy, Pushover, or plain
SMTP) turns the dashboard from something you check into something that tells
you. Fires from the scheduler tick on new `critical`/`warning` insights.

**Price refresh for holdings.** Cost basis and quantity come from the Fidelity
CSV, but prices are only as fresh as your last export. A small connector hitting
a quote API on a daily schedule would keep allocation current between exports.

## Later

**Net worth goals and projections.** Given contribution rate and a return
assumption, project forward. Cheap to build on the existing snapshot history;
worth doing once there are more than a few months of real data.

**Better categorisation.** The current rules are a readable keyword list, which
is the right starting point — you can debug it. The upgrade is learned rules
from your own corrections: when you recategorise a merchant, remember it and
apply it to future transactions from that merchant. Explicitly *not* an LLM
classifier; a rule you can't inspect has no business labelling your spending.

**Document vault.** Statements, tax documents, receipts, warranties — attached
to the account or transaction they belong to. Mostly a storage and retention
question, not a hard one.

**Home lab / infrastructure panel.** Uptime and cert expiry for the services you
run, as another connector category. A natural fit given what this box already
does, and it slots into the existing connector framework without new concepts.

**Mobile view.** The layout is responsive and usable on a phone, but it isn't
*designed* for one. A focused mobile view — today's tasks, what's due, log a
reading — would be a different, smaller surface.

## Explicitly not planned

**Multi-user with sharing.** The schema is multi-tenant so tenancy never has to
be retrofitted, but permissions, invitations and shared-account splitting are a
different product.

**A hosted version.** The entire point is that it runs on your hardware and
holds your own credentials.

**Automatic bill payment.** Reading is a very different risk profile from
writing. Life OS tells you what's due; you pay it.

**Scraping bank sites.** Brittle, against most terms of service, and it means
holding your actual banking password. The supported paths are Plaid and file
exports.
