import Header from "../header";
import RecordView from "./record-view";

export default function RecordPage() {
  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-5xl space-y-6 p-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">Your health record</h1>
          <p className="text-muted-foreground">
            Everything we found across your documents, in one place.
          </p>
        </div>
        <RecordView />
      </main>
    </>
  );
}
