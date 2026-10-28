"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { DocumentItem, TaskItem } from "@/lib/types";

export default function TasksPage() {
  const [items, setItems] = useState<TaskItem[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [status, setStatus] = useState("proposed");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");

  async function load(next = status) {
    const body = await api<{ items: TaskItem[] }>(`/api/v1/tasks?status=${next}`);
    setItems(body.items);
  }

  useEffect(() => {
    load(status).catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load tasks."));
    api<{ items: DocumentItem[] }>("/api/v1/documents").then((body) => setDocuments(body.items)).catch(() => undefined);
  }, [status]);

  async function create(event: FormEvent) {
    event.preventDefault();
    await api("/api/v1/tasks", { method: "POST", body: JSON.stringify({ title, status: "open" }) });
    setTitle("");
    if (status !== "open") setStatus("open");
    else await load("open");
  }

  async function setTaskStatus(task: TaskItem, next: string) {
    await api(`/api/v1/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify({ status: next }) });
    await load();
  }

  async function extract(documentId: string) {
    setError("");
    try {
      await api("/api/v1/tasks/extract", { method: "POST", body: JSON.stringify({ document_id: documentId }) });
      setStatus("proposed");
      await load("proposed");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not extract tasks.");
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="kicker">Work</p>
          <h1 style={{ fontSize: "2.4rem" }}>Tasks</h1>
          <p className="muted">Extracted tasks stay proposed. A weekday such as Friday is kept as a label, not turned into a calendar date.</p>
        </div>
      </header>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      <form className="card row" onSubmit={create}>
        <label htmlFor="title">New task</label>
        <input id="title" value={title} onChange={(event) => setTitle(event.target.value)} required />
        <button className="btn btn-primary" type="submit">Add</button>
      </form>
      <div className="row" style={{ margin: "14px 0" }}>
        {["proposed", "open", "completed", "cancelled"].map((value) => (
          <button key={value} type="button" className={status === value ? "btn btn-small btn-primary" : "btn btn-small"} onClick={() => setStatus(value)}>{value}</button>
        ))}
      </div>
      {documents.length > 0 ? (
        <div className="row" style={{ marginBottom: 12 }}>
          <span className="tiny">Extract from</span>
          {documents.filter((item) => item.status === "completed").map((item) => (
            <button key={item.id} className="btn btn-small" type="button" onClick={() => void extract(item.id)}>{item.label}</button>
          ))}
        </div>
      ) : null}
      {items.length === 0 ? <p className="empty">No tasks in this view.</p> : items.map((task) => (
        <article key={task.id} className="card" style={{ marginBottom: 10 }}>
          <div className="spread">
            <h2 style={{ fontSize: "1.3rem" }}>{task.title}</h2>
            <span className={`pill pill-${task.status}`}>{task.status}</span>
          </div>
          {task.due_date ? <p>Due {task.due_date}</p> : null}
          {task.due_label ? <p className="tiny">Deadline mentioned as {task.due_label}. No calendar date was inferred.</p> : null}
          {task.source_excerpt ? <p className="muted">{task.source_excerpt}</p> : null}
          <div className="row">
            {task.status === "proposed" ? <button className="btn btn-small btn-primary" type="button" onClick={() => void setTaskStatus(task, "open")}>Accept</button> : null}
            {task.status !== "completed" ? <button className="btn btn-small" type="button" onClick={() => void setTaskStatus(task, "completed")}>Complete</button> : null}
            <button className="btn btn-small btn-danger" type="button" onClick={() => void api(`/api/v1/tasks/${task.id}`, { method: "DELETE" }).then(() => load())}>Delete</button>
          </div>
        </article>
      ))}
    </>
  );
}
