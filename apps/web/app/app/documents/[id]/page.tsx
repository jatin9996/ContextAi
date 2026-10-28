"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { ApiError, api, API_URL } from "@/lib/api";
import type { DocumentItem } from "@/lib/types";

type Chunk = { id: string; chunk_index: number; content: string; page_start: number | null; section: string | null };

function Viewer() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const highlight = search.get("chunk");
  const [document, setDocument] = useState<DocumentItem | null>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [error, setError] = useState("");
  const [label, setLabel] = useState("");

  async function load() {
    const [doc, body] = await Promise.all([
      api<DocumentItem>(`/api/v1/documents/${params.id}`),
      api<{ items: Chunk[] }>(`/api/v1/documents/${params.id}/chunks`),
    ]);
    setDocument(doc);
    setLabel(doc.label);
    setChunks(body.items);
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not open the document."));
  }, [params.id]);

  async function rename(event: FormEvent) {
    event.preventDefault();
    const updated = await api<DocumentItem>(`/api/v1/documents/${params.id}`, {
      method: "PATCH",
      body: JSON.stringify({ label }),
    });
    setDocument(updated);
  }

  async function retry() {
    await api(`/api/v1/documents/${params.id}/retry`, { method: "POST" });
    await load();
  }

  async function remove() {
    if (!window.confirm("Delete this document and its indexed passages?")) return;
    await api(`/api/v1/documents/${params.id}`, { method: "DELETE" });
    window.location.href = "/app/documents";
  }

  async function download() {
    const response = await fetch(`${API_URL}/api/v1/documents/${params.id}/file`, { credentials: "include" });
    if (!response.ok) {
      setError("Could not download the original file.");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = document?.filename || "document";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (error) return <p className="error-banner" role="alert">{error}</p>;
  if (!document) return <p>Loading document…</p>;

  return (
    <>
      <p className="tiny"><Link href="/app/documents">All documents</Link></p>
      <header className="page-header">
        <div>
          <p className="kicker">{document.filename}</p>
          <h1 style={{ fontSize: "2.2rem" }}>{document.label}</h1>
          <span className={`pill pill-${document.status}`}>{document.status}</span>
          {document.error_message ? <p className="error">{document.error_message}</p> : null}
        </div>
        <div className="row">
          <button className="btn" type="button" onClick={() => void download()}>Download</button>
          {(document.status === "failed" || document.status === "cancelled") ? <button className="btn" type="button" onClick={() => void retry()}>Retry</button> : null}
          <button className="btn btn-danger" type="button" onClick={() => void remove()}>Delete</button>
        </div>
      </header>
      <form className="row" onSubmit={rename}>
        <label htmlFor="label">Label</label>
        <input id="label" value={label} onChange={(event) => setLabel(event.target.value)} />
        <button className="btn btn-small" type="submit">Save label</button>
      </form>
      <section style={{ marginTop: 16 }}>
        {chunks.length === 0 ? <p className="empty">No indexed text yet.</p> : chunks.map((chunk) => (
          <article key={chunk.id} id={chunk.id} className="card" style={{ marginBottom: 10, outline: highlight === chunk.id ? "2px solid #c6a15b" : undefined }}>
            <div className="tiny">{chunk.section || "Section"} {chunk.page_start ? `· page ${chunk.page_start}` : ""}</div>
            <p style={{ whiteSpace: "pre-wrap" }}>{chunk.content}</p>
          </article>
        ))}
      </section>
    </>
  );
}

export default function DocumentViewerPage() {
  return <Suspense fallback={<p>Loading document…</p>}><Viewer /></Suspense>;
}
