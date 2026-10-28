"use client";

import Link from "next/link";

const points = [
  "Answers cite the passage they came from.",
  "Memories stay separate from document evidence.",
  "Extracted tasks stay proposed until you accept them.",
];

export function AuthFrame({ children }: { children: React.ReactNode }) {
  return (
    <main className="auth-stage" id="main">
      <aside className="auth-aside">
        <Link href="/" className="brand"><span className="mark" aria-hidden="true" /> ContextAI</Link>
        <div>
          <p className="kicker">Personal knowledge</p>
          <h2>Your documents, with the claim still attached.</h2>
          <ul>
            {points.map((point) => <li key={point}>{point}</li>)}
          </ul>
        </div>
        <p className="tiny">Sessions stay on the server. The model key never reaches the browser.</p>
      </aside>
      <div className="auth-wrap">{children}</div>
    </main>
  );
}
