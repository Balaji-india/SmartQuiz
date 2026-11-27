import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { MasteryView } from "./view";

export default function MasteryPage() {
  return (
    <Suspense fallback={<Page><Loading /></Page>}>
      <MasteryView />
    </Suspense>
  );
}
