"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { AuthFrame } from "@/components/AuthFrame";
import { ApiError, api } from "@/lib/api";

function VerifyForm() {
  const params = useSearchParams();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const result = await api<{ message: string }>("/api/v1/auth/verify-email", {
        method: "POST",
        body: JSON.stringify({ token: form.get("token") }),
      });
      setMessage(result.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not verify the email.");
    }
  }

  return (
    <form className="card auth-card" onSubmit={onSubmit}>
      <h1 style={{ fontSize: "2.2rem" }}>Verify email</h1>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {message ? <p className="banner">{message}</p> : null}
      <div className="field">
        <label htmlFor="token">Verification token</label>
        <input id="token" name="token" defaultValue={params.get("token") ?? ""} required />
      </div>
      <button className="btn btn-primary" type="submit">Verify</button>
      <p className="tiny"><Link href="/app">Back to the workspace</Link></p>
    </form>
  );
}

export default function VerifyEmailPage() {
  return (
    <AuthFrame>
      <Suspense fallback={<p>Loading…</p>}>
        <VerifyForm />
      </Suspense>
    </AuthFrame>
  );
}
