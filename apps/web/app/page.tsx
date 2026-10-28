import Link from "next/link";
import { AuthCtas } from "@/components/AuthCtas";

const modules = [
  ["Documents", "Upload PDF, text, Markdown, or DOCX. Processing continues after the request returns."],
  ["Grounded chat", "Answers cite retrieved passages and say when the documents do not establish a claim."],
  ["Search", "Hybrid keyword and vector search, scoped to the signed-in user."],
  ["Memory", "Explicit facts stay separate from document evidence and model suggestions."],
  ["Tasks", "Extracted work stays proposed until you accept it. Deadlines are not invented."],
  ["Tools", "The model can request actions. Destructive updates wait for confirmation."],
  ["Evaluation", "A labelled sample set reports recall, citation support, and abstention."],
  ["Isolation", "Every private read and write checks the owner. Sessions live on the server."],
];

export default function LandingPage() {
  return (
    <main className="landing" id="main">
      <nav className="landing-nav spread">
        <div className="brand"><span className="mark" aria-hidden="true" /> ContextAI</div>
        <div className="row"><AuthCtas /></div>
      </nav>
      <section className="hero">
        <div>
          <p className="kicker">Personal knowledge assistant</p>
          <h1>Answers that stay attached to your evidence.</h1>
          <p className="lede">
            Upload a project brief, ask a question, and ContextAI retrieves the supporting passages,
            cites them, and keeps that conversation for the next time you return.
          </p>
          <div className="row">
            <AuthCtas />
          </div>
        </div>
        <aside className="hero-card">
          <p className="kicker">A working path</p>
          <ol>
            <li>Create an account.</li>
            <li>Upload a PDF or the sample brief.</li>
            <li>Wait until processing completes.</li>
            <li>Ask a question and inspect the citations.</li>
            <li>Come back later. The conversation is still there.</li>
          </ol>
        </aside>
      </section>
      <section className="steps">
        <article className="card"><h2>Retrieve</h2><p className="muted">Vector search and keyword search run together, then a reranker may only reorder what was already retrieved.</p></article>
        <article className="card"><h2>Separate</h2><p className="muted">Document evidence, saved memory, and model suggestions are labeled differently and stored differently.</p></article>
        <article className="card"><h2>Measure</h2><p className="muted">A fixed sample set shows whether retrieval and abstention still behave after a change. The score is not a production guarantee.</p></article>
      </section>
      <section>
        <h2 style={{ margin: "36px 0 8px" }}>What the workspace includes</h2>
        <div className="module-grid">
          {modules.map(([title, copy]) => (
            <article className="card" key={title}><h3>{title}</h3><p className="muted">{copy}</p></article>
          ))}
        </div>
      </section>
    </main>
  );
}
