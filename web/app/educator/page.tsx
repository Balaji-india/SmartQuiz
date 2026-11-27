import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { EducatorView } from "./view";

export default function EducatorPage() {
  return (
    <Suspense fallback={<Page><Loading /></Page>}>
      <EducatorView />
    </Suspense>
  );
}
