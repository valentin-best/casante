import Header from "./header";
import Uploader from "./uploader";

export default function Home() {
  return (
    <>
      <Header />
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
