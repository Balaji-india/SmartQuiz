import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { ReviewView } from "./view";

export default function ReviewPage() {
  return (
    <Suspense fallback={<Page><Loading /></Page>}>
      <ReviewView />
    </Suspense>
  );
}
