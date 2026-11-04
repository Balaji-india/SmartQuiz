import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { QuizView } from "./view";

export default function QuizPage() {
  return (
    <Suspense fallback={<Page><Loading /></Page>}>
      <QuizView />
    </Suspense>
  );
}
