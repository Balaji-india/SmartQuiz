import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { DocumentView } from "./view";

export default function DocumentPage() {
  return (
    <Suspense fallback={<Page><Loading /></Page>}>
      <DocumentView />
    </Suspense>
  );
}
