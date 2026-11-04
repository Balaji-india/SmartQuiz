import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { VerifyView } from "./view";

export default function VerifyPage() {
  return (
    <Suspense fallback={<Page authed={false}><Loading /></Page>}>
      <VerifyView />
    </Suspense>
  );
}
