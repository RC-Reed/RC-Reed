import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Field, inputClass } from "../components/ui";
import { get, post, setToken } from "../lib/api";

type Status = { registered: boolean; user_count: number };

export default function Login() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<Status | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get<Status>("/auth/status")
      .then(setStatus)
      .catch(() => setStatus({ registered: true, user_count: 1 }));
  }, []);

  const isSetup = status?.registered === false;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const path = isSetup ? "/auth/register" : "/auth/login";
      const body = isSetup ? { email, password, display_name: displayName } : { email, password };
      const result = await post<{ access_token: string }>(path, body);
      setToken(result.access_token);
      navigate("/", { replace: true });
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-900 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-series-1 text-lg font-bold text-white">
            L
          </span>
          <h1 className="text-lg font-semibold text-slate-50">
            {isSetup ? "Set up Life OS" : "Life OS"}
          </h1>
          <p className="mt-1 text-xs text-muted">
            {isSetup
              ? "Create the operator account. Registration closes after this."
              : "Sign in to your instance."}
          </p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-xl border border-ink-700 bg-ink-800 p-6"
        >
          <Field label="Email">
            <input
              type="email"
              required
              autoComplete="username"
              className={inputClass}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>

          {isSetup && (
            <Field label="Display name">
              <input
                type="text"
                className={inputClass}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </Field>
          )}

          <Field
            label="Password"
            help={isSetup ? "At least 10 characters." : undefined}
          >
            <input
              type="password"
              required
              autoComplete={isSetup ? "new-password" : "current-password"}
              className={inputClass}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>

          {error && (
            <p className="rounded-lg border border-status-critical/40 bg-status-critical/10 px-3 py-2 text-xs text-status-critical">
              {error}
            </p>
          )}

          <Button type="submit" variant="primary" disabled={busy} className="w-full py-2 text-sm">
            {busy ? "Working…" : isSetup ? "Create account" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
