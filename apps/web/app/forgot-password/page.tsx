"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { AuthFrame } from "@/components/AuthFrame";
import { ApiError, api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [message, setMessage] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const result = await api<{ message: string; dev_token?: string; email_sent?: boolean }>("/api/v1/auth/password/forgot", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email") }),
      });
      setMessage(result.message);
      setToken(result.dev_token ?? "");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start a reset.");
    }
  }

  return (
    <AuthFrame>
      <form className="card auth-card" onSubmit={onSubmit}>
        <h1 style={{ fontSize: "2.2rem" }}>Reset password</h1>
        <p className="muted">If the email matches an account, a reset link is emailed. Until mail is configured, local development shows the link here.</p>
        {error ? <p className="error-banner" role="alert">{error}</p> : null}
        {message ? <p className="banner">{message}</p> : null}
        {token ? <p className="banner">Dev reset token: <Link href={`/reset-password?token=${encodeURIComponent(token)}`}>continue</Link></p> : null}
        <div className="field"><label htmlFor="email">Email</label><input id="email" name="email" type="email" required /></div>
        <button className="btn btn-primary" type="submit">Request reset</button>
        <p className="tiny"><Link href="/login">Back to sign in</Link></p>
      </form>
    </AuthFrame>
  );
}
