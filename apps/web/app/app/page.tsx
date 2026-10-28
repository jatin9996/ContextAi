"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Dashboard>("/api/v1/dashboard")
      .then(setData)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load the dashboard."));
  }, []);

  if (error) return <p className="error-banner" role="alert">{error}</p>;
  if (!data) return <p className="muted">Loading your workspace…</p>;

  return (
    <>
      <header className="page-header">
        <div>
          <p className="kicker">Workspace</p>
          <h1 style={{ fontSize: "2.6rem" }}>Hello, {data.user.display_name}</h1>
        </div>
        <div className="row">
          <Link className="btn btn-primary" href="/app/chat">New conversation</Link>
          <Link className="btn" href="/app/documents">Upload</Link>
        </div>
      </header>
      <section className="stat-grid">
        <article className="stat"><div className="tiny">Documents</div><strong>{data.counts.documents}</strong></article>
        <article className="stat"><div className="tiny">Conversations</div><strong>{data.counts.conversations}</strong></article>
        <article className="stat"><div className="tiny">Active memories</div><strong>{data.counts.memories}</strong></article>
        <article className="stat"><div className="tiny">Open tasks</div><strong>{data.counts.open_tasks}</strong></article>
      </section>
      <section className="dash-grid" style={{ marginTop: 16 }}>
        <article className="card">
          <h2>Recent conversations</h2>
          {data.recent_conversations.length === 0 ? <p className="empty">No conversations yet.</p> : (
            <div className="list">
              {data.recent_conversations.map((item) => (
                <Link key={item.id} href={`/app/chat/${item.id}`}>{item.title}</Link>
              ))}
            </div>
          )}
        </article>
        <article className="card">
          <h2>Activity</h2>
          {data.activity.length === 0 ? <p className="empty">Activity will show up after you upload or chat.</p> : (
            <div className="list">
              {data.activity.map((item) => <div key={item.id} className="item-row"><span>{item.summary}</span></div>)}
            </div>
          )}
        </article>
      </section>
      <section className="split" style={{ marginTop: 16 }}>
        <article className="card">
          <h2>Documents</h2>
          {data.processing.length === 0 ? <p className="muted">Nothing is waiting to be processed.</p> : data.processing.map((item) => (
            <div key={item.id} className="item-row">
              <Link href={`/app/documents/${item.id}`}>{item.label}</Link>
              <span className={`pill pill-${item.status}`}>{item.status}</span>
            </div>
          ))}
        </article>
        <article className="card">
          <h2>Tasks waiting</h2>
          {data.pending_tasks.length === 0 ? <p className="muted">No proposed or open tasks.</p> : data.pending_tasks.map((task) => (
            <div key={task.id} className="item-row"><span>{task.title}</span><span className={`pill pill-${task.status}`}>{task.status}</span></div>
          ))}
        </article>
      </section>
    </>
  );
}
