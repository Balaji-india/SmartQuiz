import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { MetricsView } from "./view";

export default function MetricsPage() {
  return (
    <Suspense fallback={<Page><Loading /></Page>}>
      <MetricsView />
    </Suspense>
  );
}
