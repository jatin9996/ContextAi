"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

const links = [
  ["/app", "Dashboard"],
  ["/app/chat", "Assistant"],
  ["/app/documents", "Knowledge"],
  ["/app/search", "Search"],
  ["/app/memories", "Memory"],
  ["/app/tasks", "Tasks"],
  ["/app/evaluation", "Evaluation"],
  ["/app/settings", "Settings"],
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ user: User }>("/api/v1/auth/me")
      .then((body) => setUser(body.user))
      .catch(() => router.replace("/login"));
  }, [router]);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  async function logout() {
    try {
      await api("/api/v1/auth/logout", { method: "POST" });
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign out.");
    }
  }

  return (
    <div className="shell">
      <aside className={open ? "sidebar open" : "sidebar"}>
        <Link href="/app" className="brand"><span className="mark" aria-hidden="true" /> ContextAI</Link>
        <nav aria-label="Workspace">
          {links.map(([href, label]) => {
            const active = href === "/app" ? pathname === href : pathname.startsWith(href);
            return <Link key={href} href={href} className={active ? "nav-link active" : "nav-link"}>{label}</Link>;
          })}
        </nav>
        <div className="sidebar-foot">
          <div className="tiny">{user ? user.display_name : "Loading account"}</div>
          <button className="btn btn-small" type="button" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <div className="main" id="main">
        <button className="btn btn-small menu-button" type="button" onClick={() => setOpen((value) => !value)}>
          Menu
        </button>
        {error ? <p className="error-banner" role="alert">{error}</p> : null}
        {user ? children : <p className="muted">Checking your session…</p>}
      </div>
    </div>
  );
}
