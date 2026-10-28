"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { ApiError, api } from "@/lib/api";

function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const result = await api<{ message: string }>("/api/v1/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ token: form.get("token"), password: form.get("password") }),
      });
      setMessage(result.message);
      setTimeout(() => router.push("/login"), 700);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reset the password.");
    }
  }

  return (
    <form className="card auth-card" onSubmit={onSubmit}>
      <h1 style={{ fontSize: "2.2rem" }}>Choose a new password</h1>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {message ? <p className="banner">{message}</p> : null}
      <div className="field"><label htmlFor="token">Reset token</label><input id="token" name="token" defaultValue={params.get("token") ?? ""} required /></div>
      <div className="field"><label htmlFor="password">New password</label><input id="password" name="password" type="password" autoComplete="new-password" required /></div>
      <button className="btn btn-primary" type="submit">Update password</button>
      <p className="tiny"><Link href="/login">Back to sign in</Link></p>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="auth-wrap" id="main">
      <Suspense fallback={<p>Loading reset form…</p>}>
        <ResetForm />
      </Suspense>
    </main>
  );
}
