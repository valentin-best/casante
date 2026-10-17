import { DocumentStatus } from "./document";

// Stand-in for the API until #13 lands: walks through the pipeline statuses
// with random delays. Replace with upload + polling, keeping this signature.
export function simulateProcessing(
  onStatus: (s: DocumentStatus) => void,
): () => void {
  const steps: DocumentStatus[] = [
    "reading",
    "extracting",
    Math.random() < 0.1 ? "failed" : "done",
  ];
  let timer: ReturnType<typeof setTimeout>;

  function next(i: number) {
    timer = setTimeout(
      () => {
        onStatus(steps[i]);
        if (i + 1 < steps.length) next(i + 1);
      },
      1000 + Math.random() * 2000,
    );
  }

  next(0);
  return () => clearTimeout(timer);
}
