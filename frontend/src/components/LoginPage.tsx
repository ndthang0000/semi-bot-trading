import { TrendingUp } from "lucide-react";
import { type FormEvent, useState } from "react";
import { login, setStoredRefreshToken } from "../api/auth";
import { useAuthStore } from "../store/authStore";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const setTokens = useAuthStore((s) => s.setTokens);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setLoading(true);
    setError(null);
    try {
      const data = await login(username.trim(), password);
      setStoredRefreshToken(data.refresh_token);
      setTokens(data.access_token, data.username);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid h-dvh place-items-center bg-ink-950 px-4">
      <div className="w-full max-w-sm">
        {/* Logo / title */}
        <div className="mb-8 flex flex-col items-center gap-2 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400">
            <TrendingUp size={24} />
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-100">Semi Bot Trading</h1>
          <p className="text-sm text-slate-500">Sign in to access your dashboard</p>
        </div>

        {/* Card */}
        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-ink-700 bg-ink-900 p-6 shadow-2xl"
        >
          {/* Username */}
          <div className="mb-4">
            <label className="mb-1.5 block text-xs font-medium text-slate-400" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loading}
              className="w-full rounded-lg border border-ink-700 bg-ink-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 outline-none transition focus:border-amber-500/60 focus:ring-1 focus:ring-amber-500/30 disabled:opacity-50"
              placeholder="admin"
            />
          </div>

          {/* Password */}
          <div className="mb-5">
            <label className="mb-1.5 block text-xs font-medium text-slate-400" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              className="w-full rounded-lg border border-ink-700 bg-ink-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 outline-none transition focus:border-amber-500/60 focus:ring-1 focus:ring-amber-500/30 disabled:opacity-50"
              placeholder="••••••••"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="mb-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="w-full rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-semibold text-ink-950 transition hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
