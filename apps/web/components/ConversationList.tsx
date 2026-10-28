"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Conversation } from "@/lib/types";

export function ConversationList({ activeId }: { activeId?: string }) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    api<{ items: Conversation[] }>("/api/v1/conversations").then((body) => setItems(body.items)).catch(() => setItems([]));
  }, [activeId]);

  async function create() {
    setPending(true);
    const created = await api<{ id: string }>("/api/v1/conversations", { method: "POST", body: JSON.stringify({}) });
    window.location.href = `/app/chat/${created.id}`;
  }

  return (
    <aside className="chat-list">
      <div className="spread">
        <strong>Conversations</strong>
        <button className="btn btn-small btn-primary" type="button" disabled={pending} onClick={() => void create()}>New</button>
      </div>
      <div className="list">
        {items.length === 0 ? <p className="empty">Start a conversation to ask about your documents.</p> : items.map((item) => (
          <Link key={item.id} href={`/app/chat/${item.id}`} className={item.id === activeId ? "nav-link active" : ""}>
            {item.title}
          </Link>
        ))}
      </div>
    </aside>
  );
}
