# Security model

This system holds account balances, transaction history and health data. Worth
being deliberate about.

## Threat model

What it's designed against:

- **Loss of the database alone** (a stolen backup, a snapshot on the wrong
  disk). Connector credentials are encrypted with a key held outside the
  database, so a dump on its own yields no usable secrets.
- **Credential replay from the UI.** Secrets are write-only across the API:
  once stored, no endpoint returns them.
- **Casual network exposure.** Nothing is published beyond the web container by
  default, and there is no third-party analytics, telemetry or error reporting.

What it is **not** designed against, and you should not pretend otherwise:

- **A compromised host.** Anything running as your user can read the vault key.
- **Exposing this to the open internet without TLS and a reverse proxy.** Don't.
- **A malicious operator.** There's one account by design.

## Authentication

- Passwords hashed with **Argon2id** (passlib). Minimum 10 characters.
- Sessions are **HS256 JWTs**, 12-hour default lifetime, signed with
  `LIFEOS_SECRET_KEY`. There's no refresh-token flow — for a single-operator
  system it adds moving parts without adding safety.
- **Registration closes after the first account.** The bootstrap endpoint
  returns 403 once a user exists; further accounts are created deliberately
  with `python -m app.seed`.
- Login verifies against a dummy hash when the email doesn't exist, so a wrong
  email and a wrong password take the same time to answer.
- The token lives in `localStorage`. This is a same-origin, single-operator app,
  so a cookie would buy nothing extra and cost a CSRF story. It does mean XSS
  would expose the token — which is why the frontend has no `dangerouslySetInnerHTML`
  and no user-supplied HTML anywhere.

## The credential vault

Connector secrets (Plaid tokens, GitHub PATs, calendar URLs) are serialised to
JSON, encrypted with **Fernet** (AES-128-CBC + HMAC-SHA256), and stored as one
opaque blob on the connection row.

The key comes from `LIFEOS_VAULT_KEY`, or is generated on first boot into
`api/data/vault.key` with mode `0600`.

**Back that key up somewhere other than the machine it's on.** Losing it doesn't
corrupt anything — decryption fails closed and returns `{}` — but you re-enter
every credential.

Secrets never leave the server: `ConnectionOut` exposes `has_secrets: bool` and
nothing more, and a partial update merges with what's stored rather than
overwriting the fields the form didn't resend.

## Device push authentication

Your phone can't hold a rotating JWT, so `POST /api/v1/ingest/health`
authenticates with a long random ingest token (`X-Ingest-Token` header, or
`?token=` for clients that can't set headers), compared with
`hmac.compare_digest`. It's generated on first boot and shown on the
Connections page.

That token grants exactly one thing: the ability to write health data. It can't
read anything.

## Multi-tenancy

Every top-level table carries `user_id`, and every route filters on the
authenticated user — a cross-user fetch returns 404, not 403, so IDs aren't
confirmable. `tests/test_api.py::test_users_cannot_touch_each_others_accounts`
pins this. It's built in even though there's one user, because retrofitting
tenancy is how data leaks get written.

## Audit trail

`audit_events` records logins, failed logins, and connection create/update/delete
with source IP. `sync_runs` records every sync attempt and its outcome. Both are
cheap to write and are the first place to look when something is off.

## Outbound network

The only outbound calls are the ones a connector you configured makes:
`api.plaid.com` (or sandbox), `api.github.com`, and whatever ICS URL you
supplied. No telemetry, no crash reporting, no CDN calls at runtime — the
frontend bundles its assets.

## Deploying beyond localhost

The compose file publishes only the web container, on port 8080. Before it
leaves your LAN:

1. **Terminate TLS** at a reverse proxy (Caddy makes this two lines; nginx or
   Traefik are fine). Never expose port 8080 directly.
2. **Set real keys.** `LIFEOS_SECRET_KEY` and `LIFEOS_VAULT_KEY` must be
   generated, not the placeholders:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. **Set `LIFEOS_CORS_ORIGINS`** to your actual origin. Don't use `*`.
4. **Prefer not to expose it at all.** A WireGuard or Tailscale tunnel gives
   you phone access — including the Apple Health push — without a public
   listener. For a personal finance dashboard this is the right default.
5. **Back up** the Postgres volume *and* `api/data/vault.key`. A database
   backup without the key is only half a backup.

## Reporting

It's your instance. If you find something wrong with the design, the fix is a
commit.
