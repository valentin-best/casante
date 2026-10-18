// Mirrors GET /record (api/app/record.py) and the extraction schema
// (api/app/pipeline/schemas.py).

export type DocumentType =
  | "discharge_summary"
  | "clinic_letter"
  | "lab_report"
  | "prescription"
  | "other";

export type Source = {
  document_id: string;
  evidence: string[];
};

type Sourced = { sources: Source[] };

export type RecordDocument = {
  id: string;
  filename: string;
  type: DocumentType | null;
  provider: string | null;
  date: string | null;
};

export type Medication = Sourced & {
  name: string;
  dose: string | null;
  route: string | null;
  frequency: string | null;
  status: "active" | "stopped" | "changed" | "unknown" | null;
  start_date: string | null;
  stop_date: string | null;
};

export type Allergy = Sourced & {
  substance: string;
  reaction: string | null;
  severity: "mild" | "moderate" | "severe" | "unknown" | null;
};

export type Condition = Sourced & {
  name: string;
  status: "active" | "resolved" | "unknown" | null;
  onset_date: string | null;
};

export type Lab = Sourced & {
  test: string;
  value: number | null;
  unit: string | null;
  reference_range: string | null;
  flag: "high" | "low" | "normal" | null;
  date: string | null;
};

export type Procedure = Sourced & {
  name: string;
  date: string | null;
};

export type HealthRecord = {
  documents: RecordDocument[];
  medications: Medication[];
  allergies: Allergy[];
  conditions: Condition[];
  labs: Lab[];
  procedures: Procedure[];
  conflicts: unknown[];
};

export const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  discharge_summary: "Discharge summary",
  clinic_letter: "Clinic letter",
  lab_report: "Lab report",
  prescription: "Prescription",
  other: "Document",
};

export type TimelineEvent = {
  key: string;
  date: string;
  label: string;
  detail: string | null;
};

// Dated events across the record, newest first.
export function buildTimeline(record: HealthRecord): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  const add = (date: string | null, label: string, detail: string | null) => {
    if (date) {
      events.push({ key: `${events.length}`, date, label, detail });
    }
  };

  for (const doc of record.documents) {
    add(
      doc.date,
      doc.type ? DOCUMENT_TYPE_LABEL[doc.type] : "Document",
      doc.provider ?? doc.filename,
    );
  }
  for (const med of record.medications) {
    add(med.start_date, `Started ${med.name}`, med.dose);
    add(med.stop_date, `Stopped ${med.name}`, null);
  }
  for (const condition of record.conditions) {
    add(condition.onset_date, `Diagnosed with ${condition.name}`, null);
  }
  for (const procedure of record.procedures) {
    add(procedure.date, procedure.name, "Procedure");
  }

  return events.sort((a, b) => b.date.localeCompare(a.date));
}

export function formatDate(date: string) {
  return new Date(`${date}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
