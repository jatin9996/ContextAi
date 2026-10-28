"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { DocumentItem } from "@/lib/types";

export default function DocumentsPage() {
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    const body = await api<{ items: DocumentItem[] }>("/api/v1/documents");
    setItems(body.items);
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load documents."));
  }, []);

  useEffect(() => {
    if (!items.some((item) => item.status === "queued" || item.status === "processing")) return;
    const timer = window.setInterval(() => {
      load().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [items]);

  async function addSample() {
    setError("");
    setNotice("");
    try {
      await api("/api/v1/documents/sample", { method: "POST" });
      setNotice("Sample brief added. Processing continues in the background.");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add the sample brief.");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setError("");
    setNotice("");
    try {
      await api("/api/v1/documents", { method: "POST", body: data });
      form.reset();
      setNotice("Upload received. Processing continues in the background.");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="kicker">Knowledge base</p>
          <h1 style={{ fontSize: "2.4rem" }}>Documents</h1>
        </div>
      </header>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
      <form className="card" onSubmit={onSubmit}>
        <label htmlFor="file">Upload a PDF, TXT, Markdown, or DOCX file up to 20 MB.</label>
        <input id="file" name="file" type="file" accept=".pdf,.txt,.md,.docx,application/pdf,text/plain,text/markdown" required />
        <div className="row">
          <button className="btn btn-primary" type="submit">Upload</button>
          <button className="btn" type="button" onClick={() => void addSample()}>Add the sample brief</button>
        </div>
      </form>
      <section className="card" style={{ marginTop: 16 }}>
        {items.length === 0 ? <p className="empty">No documents yet. The sample brief in the repository is a good first file.</p> : items.map((item) => (
          <div key={item.id} className="item-row">
            <Link href={`/app/documents/${item.id}`}>{item.label}</Link>
            <span className={`pill pill-${item.status}`}>{item.status}</span>
          </div>
        ))}
      </section>
    </>
  );
}
