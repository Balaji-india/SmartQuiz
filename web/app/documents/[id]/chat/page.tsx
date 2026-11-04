import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { ChatView } from "./view";

export default function ChatPage() {
  return (
    <Suspense fallback={<Page><Loading /></Page>}>
      <ChatView />
    </Suspense>
  );
}
