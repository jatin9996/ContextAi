import Link from "next/link";
import { AuthCtas } from "@/components/AuthCtas";

const modules = [
  ["01", "Documents", "PDF, text, Markdown, and DOCX. Processing finishes after the upload returns."],
  ["02", "Grounded chat", "Answers cite the passage, or say the documents do not establish the claim."],
  ["03", "Search", "Keyword and vector search, limited to the signed-in account."],
  ["04", "Memory", "Saved facts stay separate from document evidence and model suggestions."],
  ["05", "Tasks", "Extracted work stays proposed. A weekday is kept as a label, not a calendar date."],
  ["06", "Evaluation", "A fixed sample set reports recall, citations, and abstention for that set only."],
];

export default function LandingPage() {
  return (
    <div className="landing" id="main">
      <header className="landing-nav">
        <Link href="/" className="brand"><span className="mark" aria-hidden="true" /> ContextAI</Link>
        <nav className="landing-links" aria-label="Page">
          <a href="#product">Product</a>
          <a href="#workspace">Workspace</a>
        </nav>
        <div className="row"><AuthCtas /></div>
      </header>

      <section className="hero">
        <div>
          <p className="kicker">Personal knowledge assistant</p>
          <h1>Answers that stay attached to your evidence.</h1>
          <p className="lede">
            Upload a project brief, ask a question, and ContextAI retrieves the supporting passages,
            cites them, and keeps that conversation for the next time you return.
          </p>
          <div className="row hero-actions">
            <AuthCtas />
            <a className="btn" href="#workspace">See the workspace</a>
          </div>
        </div>
        <aside className="preview" aria-hidden="true">
          <div className="preview-bar"><span /><span /><span /></div>
          <p className="preview-q">What is the specification code?</p>
          <div className="preview-a">
            <p>The brief identifies the code as <strong>SPEC-CTX-1842</strong>. Semantic search uses pgvector with 384-dimensional embeddings.</p>
            <div className="citation">
              <strong>[S1] Project brief · page 1</strong>
              <div>Specification code: SPEC-CTX-1842</div>
            </div>
          </div>
        </aside>
      </section>

      <section className="steps" id="product">
        <article className="card">
          <p className="kicker">Retrieve</p>
          <h2>Search the file, then the wording.</h2>
          <p className="muted">Vector search and keyword search run together. Later ranking can only reorder passages that were already retrieved.</p>
        </article>
        <article className="card">
          <p className="kicker">Separate</p>
          <h2>Evidence is not a memory.</h2>
          <p className="muted">Document passages, saved facts, and model suggestions are stored and labeled differently.</p>
        </article>
        <article className="card">
          <p className="kicker">Measure</p>
          <h2>A score for this set.</h2>
          <p className="muted">A fixed sample shows whether retrieval and abstention still behave after a change. It is not a production guarantee.</p>
        </article>
      </section>

      <section id="workspace">
        <div className="section-head">
          <div>
            <p className="kicker">Workspace</p>
            <h2>Everything stays inside one account.</h2>
          </div>
          <Link className="btn btn-primary" href="/register">Create an account</Link>
        </div>
        <div className="module-grid">
          {modules.map(([index, title, copy]) => (
            <article className="card module-card" key={title}>
              <span className="index">{index}</span>
              <h3>{title}</h3>
              <p className="muted">{copy}</p>
            </article>
          ))}
        </div>
      </section>

      <footer className="landing-foot">
        <span className="brand"><span className="mark" aria-hidden="true" /> ContextAI</span>
        <span className="tiny">Citations, memory, and tasks for one person’s documents.</span>
      </footer>
    </div>
  );
}
