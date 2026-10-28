"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { ApiError, api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError("");
    try {
      await api("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      router.push("/app");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="auth-wrap" id="main">
      <form className="card auth-card" onSubmit={onSubmit}>
        <p className="kicker">ContextAI</p>
        <h1 style={{ fontSize: "2.4rem" }}>Sign in</h1>
        <p className="muted">Use the email and password for your workspace.</p>
        {error ? <p className="error-banner" role="alert">{error}</p> : null}
        <div className="field"><label htmlFor="email">Email</label><input id="email" name="email" type="email" autoComplete="email" required /></div>
        <div className="field"><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" required /></div>
        <button className="btn btn-primary" type="submit" disabled={pending}>{pending ? "Signing in…" : "Sign in"}</button>
        <p className="tiny"><Link href="/forgot-password">Forgot password</Link> · <Link href="/register">Create an account</Link></p>
      </form>
    </main>
  );
}
