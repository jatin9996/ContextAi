"use client";

import { useParams } from "next/navigation";
import { ChatScreen } from "@/components/ChatScreen";

export default function ConversationPage() {
  const params = useParams<{ id: string }>();
  return <ChatScreen conversationId={params.id} />;
}
