"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { MemoryItem } from "@/lib/types";

export default function MemoriesPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [status, setStatus] = useState("active");
  const [content, setContent] = useState("");
  const [error, setError] = useState("");

  async function load(next = status) {
    const body = await api<{ items: MemoryItem[] }>(`/api/v1/memories?status=${next}`);
    setItems(body.items);
  }

  useEffect(() => {
    load(status).catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load memories."));
  }, [status]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const result = await api<{ memory: MemoryItem; outcome: string }>("/api/v1/memories", {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      setContent("");
      if (result.memory.status !== "active") setStatus(result.memory.status);
      await load(result.memory.status === "active" ? status : result.memory.status);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the memory.");
    }
  }

  async function saveEdit(item: MemoryItem, next: string) {
    await api(`/api/v1/memories/${item.id}`, { method: "PATCH", body: JSON.stringify({ content: next }) });
    await load();
  }

  async function remove(id: string) {
    if (!window.confirm("Delete this memory? It will leave retrieval immediately.")) return;
    await api(`/api/v1/memories/${id}`, { method: "DELETE" });
    await load();
  }

  async function resolve(id: string, action: string) {
    await api(`/api/v1/memories/${id}/resolve`, { method: "POST", body: JSON.stringify({ action }) });
    await load();
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="kicker">Personal memory</p>
          <h1 style={{ fontSize: "2.4rem" }}>Saved memories</h1>
          <p className="muted">Only active memories are used in answers. Suggestions and conflicts stay out until you decide.</p>
        </div>
      </header>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      <form className="card" onSubmit={create}>
        <label htmlFor="memory">Remember</label>
        <textarea id="memory" value={content} onChange={(event) => setContent(event.target.value)} placeholder="I prefer Python for AI backend development." />
        <button className="btn btn-primary" type="submit">Save memory</button>
      </form>
      <div className="row" style={{ margin: "14px 0" }}>
        {["active", "suggested", "conflict_pending", "superseded", "all"].map((value) => (
          <button key={value} className={status === value ? "btn btn-small btn-primary" : "btn btn-small"} type="button" onClick={() => setStatus(value)}>{value.replace("_", " ")}</button>
        ))}
      </div>
      {items.length === 0 ? <p className="empty">Nothing in this view.</p> : items.map((item) => (
        <MemoryRow key={item.id} item={item} onSave={saveEdit} onDelete={remove} onResolve={resolve} />
      ))}
    </>
  );
}

function MemoryRow({
  item,
  onSave,
  onDelete,
  onResolve,
}: {
  item: MemoryItem;
  onSave: (item: MemoryItem, content: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onResolve: (id: string, action: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(item.content);
  return (
    <article className="card" style={{ marginBottom: 10 }}>
      <div className="spread">
        <span className={`pill pill-${item.status}`}>{item.status}</span>
        <span className="tiny">{item.source}</span>
      </div>
      <textarea value={editing} onChange={(event) => setEditing(event.target.value)} />
      <div className="row">
        <button className="btn btn-small" type="button" onClick={() => void onSave(item, editing)}>Save edit</button>
        {item.status === "conflict_pending" ? (
          <>
            <button className="btn btn-small btn-primary" type="button" onClick={() => void onResolve(item.id, "keep_new")}>Keep new</button>
            <button className="btn btn-small" type="button" onClick={() => void onResolve(item.id, "keep_existing")}>Keep existing</button>
          </>
        ) : null}
        {item.status === "suggested" ? <button className="btn btn-small btn-primary" type="button" onClick={() => void api(`/api/v1/memories/${item.id}`, { method: "PATCH", body: JSON.stringify({ status: "active" }) }).then(() => onSave(item, editing))}>Approve</button> : null}
        <button className="btn btn-small btn-danger" type="button" onClick={() => void onDelete(item.id)}>Delete</button>
      </div>
    </article>
  );
}
