"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { ApiError, api } from "@/lib/api";

type Group = {
  document_id: string;
  label: string;
  filename: string;
  hits: Array<{ chunk_id: string; excerpt: string; page_start: number | null; section: string | null; score: number }>;
};

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [fileType, setFileType] = useState("");
  const [groups, setGroups] = useState<Group[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const body = await api<{ groups: Group[]; diagnostics: { retrieved_count: number; retrieval_ms: number } }>("/api/v1/search", {
        method: "POST",
        body: JSON.stringify({ query, file_type: fileType || null }),
      });
      setGroups(body.groups);
      setNote(`Retrieved ${body.diagnostics.retrieved_count} candidates in ${body.diagnostics.retrieval_ms} ms.`);
      setSearched(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed.");
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="kicker">Knowledge base</p>
          <h1 style={{ fontSize: "2.4rem" }}>Search</h1>
          <p className="muted">Semantic similarity and exact identifiers are combined. Results stay inside your account.</p>
        </div>
      </header>
      <form className="card" onSubmit={onSubmit}>
        <div className="field"><label htmlFor="query">Question or identifier</label><input id="query" value={query} onChange={(event) => setQuery(event.target.value)} required /></div>
        <div className="field">
          <label htmlFor="type">File type</label>
          <select id="type" value={fileType} onChange={(event) => setFileType(event.target.value)}>
            <option value="">Any</option>
            <option value="pdf">PDF</option>
            <option value="md">Markdown</option>
            <option value="txt">Text</option>
            <option value="docx">DOCX</option>
          </select>
        </div>
        <button className="btn btn-primary" type="submit">Search</button>
      </form>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {note ? <p className="tiny">{note}</p> : null}
      <section style={{ marginTop: 16 }}>
        {searched && groups.length === 0 ? <p className="empty">No passages matched. Try an identifier from the document, or upload more material.</p> : null}
        {groups.map((group) => (
          <article key={group.document_id} className="card" style={{ marginBottom: 12 }}>
            <h2>{group.label}</h2>
            {group.hits.map((hit) => (
              <div key={hit.chunk_id} className="item-row">
                <div>
                  <div>{hit.excerpt}</div>
                  <Link href={`/app/documents/${group.document_id}?chunk=${hit.chunk_id}`}>Open passage</Link>
                </div>
                <span className="tiny">score {hit.score}</span>
              </div>
            ))}
          </article>
        ))}
      </section>
    </>
  );
}
