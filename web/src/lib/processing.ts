import { ApiError, getDocument, startProcessing, uploadDocument } from "./api";
import { DocumentStatus } from "./document";

const POLL_MS = 2000;

type OnUpdate = (status: DocumentStatus, error?: string) => void;

function message(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "Couldn't reach the server. Check your connection and try again.";
}

export function processDocument(file: File, onUpdate: OnUpdate): () => void {
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function poll(id: string) {
    try {
      const document = await getDocument(id);
      if (cancelled) return;
      onUpdate(document.status, document.error ?? undefined);
      if (document.status !== "done" && document.status !== "failed") {
        timer = setTimeout(() => poll(id), POLL_MS);
      }
    } catch (error) {
      if (!cancelled) onUpdate("failed", message(error));
    }
  }

  (async () => {
    try {
      const document = await uploadDocument(file);
      if (cancelled) return;
      await startProcessing(document.id);
      if (!cancelled) poll(document.id);
    } catch (error) {
      if (!cancelled) onUpdate("failed", message(error));
    }
  })();

  return () => {
    cancelled = true;
    clearTimeout(timer);
  };
}
