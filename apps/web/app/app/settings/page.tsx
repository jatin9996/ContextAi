"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { User } from "@/lib/types";

export default function SettingsPage() {
  const [user, setUser] = useState<User | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ user: User }>("/api/v1/auth/me").then((body) => setUser(body.user)).catch((err: unknown) => {
      setError(err instanceof ApiError ? err.message : "Could not load settings.");
    });
  }, []);

  async function sendVerification() {
    setError("");
    try {
      const result = await api<{ message: string; email_sent?: boolean; dev_token?: string }>("/api/v1/auth/verify-email/request", { method: "POST" });
      setMessage(result.email_sent ? "Verification email sent." : result.dev_token ? `Verification link token: ${result.dev_token}` : result.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the verification email.");
    }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) return;
    setError("");
    const updated = await api<{ user: User }>("/api/v1/auth/profile", {
      method: "PATCH",
      body: JSON.stringify({
        display_name: user.display_name,
        timezone: user.timezone,
        preferred_language: user.preferred_language,
        response_style: user.response_style,
        memory_enabled: user.memory_enabled,
      }),
    });
    setUser(updated.user);
    setMessage("Preferences saved.");
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const result = await api<{ message: string }>("/api/v1/auth/password/change", {
        method: "POST",
        body: JSON.stringify({ current_password: form.get("current_password"), new_password: form.get("new_password") }),
      });
      setMessage(result.message);
      event.currentTarget.reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the password.");
    }
  }

  async function removeAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!window.confirm("Delete the account and its documents, memories, tasks, and conversations?")) return;
    try {
      await api("/api/v1/auth/account", {
        method: "DELETE",
        body: JSON.stringify({ password: form.get("password"), confirmation: form.get("confirmation") }),
      });
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the account.");
    }
  }

  if (!user) return <p>Loading settings…</p>;

  return (
    <>
      <header className="page-header">
        <div>
          <p className="kicker">Account</p>
          <h1 style={{ fontSize: "2.4rem" }}>Settings</h1>
          <p className="muted">{user.email} · {user.email_verified ? "Email verified" : "Email not verified"}</p>
        </div>
        {user.email_verified ? null : (
          <button className="btn" type="button" onClick={() => void sendVerification()}>Send verification email</button>
        )}
      </header>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {message ? <p className="banner">{message}</p> : null}
      <form className="card" onSubmit={saveProfile}>
        <h2>Profile</h2>
        <div className="field"><label htmlFor="name">Display name</label><input id="name" value={user.display_name} onChange={(event) => setUser({ ...user, display_name: event.target.value })} /></div>
        <div className="field"><label htmlFor="timezone">Timezone</label><input id="timezone" value={user.timezone} onChange={(event) => setUser({ ...user, timezone: event.target.value })} /></div>
        <div className="field">
          <label htmlFor="language">Response language</label>
          <select id="language" value={user.preferred_language} onChange={(event) => setUser({ ...user, preferred_language: event.target.value })}>
            {["en", "es", "fr", "de", "hi"].map((code) => <option key={code} value={code}>{code}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="style">Response style</label>
          <select id="style" value={user.response_style} onChange={(event) => setUser({ ...user, response_style: event.target.value })}>
            {["concise", "balanced", "detailed"].map((style) => <option key={style}>{style}</option>)}
          </select>
        </div>
        <label><input type="checkbox" checked={user.memory_enabled} onChange={(event) => setUser({ ...user, memory_enabled: event.target.checked })} /> Use saved memories in answers</label>
        <div><button className="btn btn-primary" type="submit">Save preferences</button></div>
      </form>
      <form className="card" style={{ marginTop: 16 }} onSubmit={changePassword}>
        <h2>Password</h2>
        <div className="field"><label htmlFor="current">Current password</label><input id="current" name="current_password" type="password" required /></div>
        <div className="field"><label htmlFor="next">New password</label><input id="next" name="new_password" type="password" required /></div>
        <button className="btn" type="submit">Change password</button>
      </form>
      <form className="card" style={{ marginTop: 16 }} onSubmit={removeAccount}>
        <h2>Delete account</h2>
        <p className="muted">This immediately removes the account, stored files, vectors, conversations, memories, and tasks. Type DELETE to confirm.</p>
        <div className="field"><label htmlFor="password">Password</label><input id="password" name="password" type="password" required /></div>
        <div className="field"><label htmlFor="confirmation">Confirmation</label><input id="confirmation" name="confirmation" required /></div>
        <button className="btn btn-danger" type="submit">Delete account</button>
      </form>
    </>
  );
}
