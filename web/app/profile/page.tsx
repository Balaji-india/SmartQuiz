import { Suspense } from "react";
import { Page } from "@/components/shell";
import { Loading } from "@/components/ui";
import { ProfileView } from "./view";

export default function ProfilePage() {
  return (
    <Suspense fallback={<Page><Loading /></Page>}>
      <ProfileView />
    </Suspense>
  );
}
