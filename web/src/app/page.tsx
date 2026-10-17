import { createClient } from "@/lib/supabase/server";
import SignOutButton from "./sign-out-button";
import Uploader from "./uploader";

export default async function Home() {
  const client = await createClient();
  const { data } = await client.auth.getClaims();
  const email = data?.claims.email || null;

  return (
    <>
      <header className="flex items-center justify-between border-b px-6 py-3">
        <span className="font-semibold">CaSanté</span>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">{email}</span>
          <SignOutButton />
        </div>
      </header>
      <main className="mx-auto w-full max-w-2xl space-y-6 p-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">Your documents</h1>
          <p className="text-muted-foreground">
            Upload prescriptions, lab results or discharge letters. We&apos;ll
            extract medications and flag conflicts.
          </p>
          <p className="text-sm text-muted-foreground">
            Demo only: all data is synthetic. Don&apos;t upload real medical
            documents.
          </p>
        </div>
        <Uploader />
      </main>
    </>
  );
}
