"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";

type Run = {
  id: string;
  status: string;
  metrics: Record<string, number | string | null>;
  created_at: string;
  error_code: string | null;
};

type Result = {
  case_id: string;
  question: string | null;
  case_type: string | null;
  passed: boolean;
  failure_reason: string | null;
  metrics: Record<string, number | null>;
};

const targets = [
  ["Retrieval recall@5", "85% on a labelled set"],
  ["Citation support", "90% on a reviewed set"],
  ["Cross-user document access", "Zero in the security tests"],
];

export default function EvaluationPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<{ run: Run; results: Result[] } | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function load() {
    const body = await api<{ items: Run[] }>("/api/v1/evaluations/runs");
    setRuns(body.items);
    return body.items;
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load runs."));
  }, []);

  useEffect(() => {
    const active = runs.find((run) => run.status === "queued" || run.status === "running");
    if (!active) return;
    const timer = window.setInterval(() => {
      load().then((items) => {
        const current = items.find((run) => run.id === active.id);
        if (current && current.status !== "queued" && current.status !== "running") {
          void openRun(current.id);
        }
      }).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [runs]);

  async function start() {
    setPending(true);
    setError("");
    try {
      const run = await api<Run>("/api/v1/evaluations/runs", { method: "POST", body: JSON.stringify({ use_sample_corpus: true }) });
      await load();
      setSelected({ run, results: [] });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the run.");
    } finally {
      setPending(false);
    }
  }

  async function openRun(id: string) {
    const body = await api<{ run: Run; results: Result[] }>(`/api/v1/evaluations/runs/${id}`);
    setSelected(body);
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="kicker">Quality</p>
          <h1 style={{ fontSize: "2.4rem" }}>Evaluation</h1>
          <p className="muted">Runs the fixed sample brief. The numbers describe that set and the current configuration. They are not a real-world guarantee.</p>
        </div>
        <button className="btn btn-primary" type="button" disabled={pending} onClick={() => void start()}>{pending ? "Starting…" : "Run sample evaluation"}</button>
      </header>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      <section className="stat-grid">
        {targets.map(([label, value]) => <article key={label} className="stat"><div className="tiny">Target</div><strong>{label}</strong><div className="tiny">{value}</div></article>)}
      </section>
      <section className="split" style={{ marginTop: 16 }}>
        <article className="card">
          <h2>Runs</h2>
          {runs.length === 0 ? <p className="empty">No runs yet. The worker must be running. In local development the API embeds it.</p> : runs.map((run) => (
            <button key={run.id} className="item-row" type="button" onClick={() => void openRun(run.id)} style={{ width: "100%", background: "transparent", border: 0 }}>
              <span>{run.status}</span>
              <span className="tiny">{typeof run.metrics.retrieval_recall_at_5 === "number" ? `recall ${run.metrics.retrieval_recall_at_5}` : run.created_at}</span>
            </button>
          ))}
        </article>
        <article className="card">
          <h2>Selected run</h2>
          {!selected ? <p className="muted">Choose a run to see which cases failed.</p> : (
            <>
              <p className={`pill pill-${selected.run.status}`}>{selected.run.status}</p>
              {selected.run.metrics.disclaimer ? <p className="tiny">{String(selected.run.metrics.disclaimer)}</p> : null}
              <p>Failed cases: {String(selected.run.metrics.failed_cases ?? "—")}</p>
              {selected.results.map((result) => (
                <div key={result.case_id} className="item-row">
                  <span>{result.passed ? "Pass" : "Fail"} · {result.question || result.case_type}</span>
                  {!result.passed ? <span className="tiny">{result.failure_reason}</span> : null}
                </div>
              ))}
            </>
          )}
        </article>
      </section>
    </>
  );
}
