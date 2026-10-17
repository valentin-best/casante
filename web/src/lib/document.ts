export type DocumentStatus =
  "queued" | "reading" | "extracting" | "done" | "failed";

export const STATUS_PROGRESS: Record<DocumentStatus, number> = {
  queued: 0,
  reading: 33,
  extracting: 66,
  done: 100,
  failed: 100,
};

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  queued: "Queued",
  reading: "Reading",
  extracting: "Extracting",
  done: "Done",
  failed: "Failed",
};

export type UploadItem = {
  id: string;
  file: File;
  status: DocumentStatus;
  error?: string;
};
