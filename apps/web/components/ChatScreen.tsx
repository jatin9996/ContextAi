"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { ConversationList } from "@/components/ConversationList";
import { ApiError, api, streamMessage } from "@/lib/api";
import type { ChatMessage, Citation } from "@/lib/types";

export function ChatScreen({ conversationId }: { conversationId?: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("New conversation");

  useEffect(() => {
    if (!conversationId) return;
    api<{ conversation: { title: string }; messages: ChatMessage[] }>(`/api/v1/conversations/${conversationId}`)
      .then((body) => {
        setTitle(body.conversation.title);
        setMessages(body.messages);
      })
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load the conversation."));
  }, [conversationId]);

  async function ensureConversation() {
    if (conversationId) return conversationId;
    const created = await api<{ id: string }>("/api/v1/conversations", { method: "POST", body: JSON.stringify({}) });
    window.location.href = `/app/chat/${created.id}`;
    return created.id;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || !conversationId) return;
    setDraft("");
    setPending(true);
    setError("");
    setStreaming("");
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      conversation_id: conversationId,
      role: "user",
      content,
      status: "completed",
      citations: [],
      evidence: [],
      actions: [],
      diagnostics: {},
      error_code: null,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);
    try {
      await streamMessage(conversationId, content, (event) => {
        if (event.event === "token") setStreaming((value) => value + String(event.data.text ?? ""));
        if (event.event === "done") {
          const message = event.data.message as ChatMessage;
          setMessages((current) => [...current.filter((item) => item.id !== optimistic.id), optimistic, message]);
          setStreaming("");
        }
        if (event.event === "error") setError(String(event.data.message ?? "The response failed."));
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The response was interrupted.");
    } finally {
      setPending(false);
    }
  }

  async function confirmAction(operationId: string) {
    await api(`/api/v1/tools/operations/${operationId}/confirm`, { method: "POST" });
    if (conversationId) {
      const body = await api<{ messages: ChatMessage[] }>(`/api/v1/conversations/${conversationId}`);
      setMessages(body.messages);
    }
  }

  return (
    <div className={conversationId ? "chat-layout in-thread" : "chat-layout"}>
      <ConversationList activeId={conversationId} />
      <section className="thread" aria-live="polite">
        <header className="spread" style={{ padding: "12px 16px" }}>
          <h1 style={{ fontSize: "1.6rem" }}>{conversationId ? title : "New conversation"}</h1>
          {conversationId ? <Link href="/app/chat">Back</Link> : null}
        </header>
        {error ? <p className="error-banner" role="alert">{error}</p> : null}
        <div className="messages">
          {!conversationId ? (
            <div className="empty">
              <h2>Ask from your own material</h2>
              <p className="muted">Upload a document first, then ask a question. Citations stay attached to the answer.</p>
              <button className="btn btn-primary" type="button" onClick={() => void ensureConversation()}>Start conversation</button>
            </div>
          ) : null}
          {messages.map((message) => (
            <article key={message.id} className={message.role === "user" ? "bubble bubble-user" : "bubble bubble-assistant"}>
              <div>{message.content || (message.status === "failed" ? "This response failed." : "")}</div>
              {message.status !== "completed" && message.role === "assistant" ? <div className="tiny">{message.status}</div> : null}
              <Citations items={message.citations} />
              <Actions actions={message.actions} onConfirm={confirmAction} />
            </article>
          ))}
          {streaming ? <article className="bubble bubble-assistant">{streaming}</article> : null}
        </div>
        {conversationId ? (
          <form className="composer" onSubmit={onSubmit}>
            <label className="sr-only" htmlFor="composer" style={{ position: "absolute", left: "-999px" }}>Message</label>
            <textarea id="composer" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Ask about your documents. Shift+Enter for a new line." onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }} />
            <button className="btn btn-primary" type="submit" disabled={pending || !draft.trim()}>{pending ? "Working" : "Send"}</button>
          </form>
        ) : null}
      </section>
    </div>
  );
}

function Citations({ items }: { items: Citation[] }) {
  if (!items?.length) return null;
  return (
    <div className="citations">
      {items.map((item) => (
        <div key={item.marker} className="citation">
          <strong>[{item.marker}] {item.type === "memory" ? "Memory" : item.label}</strong>
          {item.page_start ? <span> · page {item.page_start}</span> : null}
          <div>{item.excerpt}</div>
          {item.document_id ? <Link href={`/app/documents/${item.document_id}?chunk=${item.chunk_id}`}>Open document</Link> : null}
        </div>
      ))}
    </div>
  );
}

function Actions({ actions, onConfirm }: { actions: Array<Record<string, string>>; onConfirm: (id: string) => Promise<void> }) {
  if (!actions?.length) return null;
  return (
    <div className="citations">
      {actions.map((action, index) => (
        <div key={`${action.type}-${index}`} className="citation">
          {action.type === "confirm_action" ? (
            <>
              <div>{action.summary}</div>
              <button className="btn btn-small btn-primary" type="button" onClick={() => void onConfirm(action.operation_id)}>Confirm</button>
            </>
          ) : (
            <>
              <div>Suggested memory, not saved yet: {action.content}</div>
              {action.content ? (
                <button
                  className="btn btn-small"
                  type="button"
                  onClick={() =>
                    void api("/api/v1/memories", {
                      method: "POST",
                      body: JSON.stringify({ content: action.content }),
                    })
                  }
                >
                  Save memory
                </button>
              ) : null}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
