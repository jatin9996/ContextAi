"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

const links: Array<[string, string, string]> = [
  ["/app", "Dashboard", "M3 4h7v7H3zM14 4h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"],
  ["/app/chat", "Assistant", "M5 6h14v9H8l-3 3z"],
  ["/app/documents", "Knowledge", "M6 4h8l4 4v12H6z"],
  ["/app/search", "Search", "M11 6a5 5 0 1 1 0 10 5 5 0 0 1 0-10zm6 10 3 3"],
  ["/app/memories", "Memory", "M12 5c4 0 7 2 7 5s-3 5-7 5-7-2-7-5 3-5 7-5z"],
  ["/app/tasks", "Tasks", "M6 7h12M6 12h12M6 17h8"],
  ["/app/evaluation", "Evaluation", "M5 16l4-4 3 3 7-8"],
  ["/app/settings", "Settings", "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"],
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="nav-icon">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

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

  const initial = user?.display_name?.trim().charAt(0).toUpperCase() || "·";

  return (
    <div className="shell">
      {open ? <button className="backdrop" type="button" aria-label="Close menu" onClick={() => setOpen(false)} /> : null}
      <aside className={open ? "sidebar open" : "sidebar"}>
        <Link href="/app" className="brand"><span className="mark" aria-hidden="true" /> ContextAI</Link>
        <nav aria-label="Workspace">
          {links.map(([href, label, icon]) => {
            const active = href === "/app" ? pathname === href : pathname.startsWith(href);
            return (
              <Link key={href} href={href} className={active ? "nav-link active" : "nav-link"}>
                <Icon d={icon} />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <div className="account-chip">
            <span className="avatar" aria-hidden="true">{initial}</span>
            <span>
              <strong>{user ? user.display_name : "Loading"}</strong>
              <span className="tiny">{user?.email ?? "Checking session"}</span>
            </span>
          </div>
          <button className="btn btn-small btn-ghost" type="button" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <div className="main" id="main">
        <div className="topbar">
          <button className="btn btn-small menu-button" type="button" onClick={() => setOpen((value) => !value)}>
            Menu
          </button>
        </div>
        {error ? <p className="error-banner" role="alert">{error}</p> : null}
        {user ? children : <p className="muted">Checking your session…</p>}
      </div>
    </div>
  );
}
