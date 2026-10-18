import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Allergy,
  Condition,
  formatDate,
  Lab,
  Medication,
  RecordDocument,
  Source,
  TimelineEvent,
} from "@/lib/record";
import { FileText } from "lucide-react";
import Link from "next/link";
import { itemHref } from "./source-panel";

type Documents = Map<string, RecordDocument>;

function Section({
  title,
  count,
  empty,
  children,
}: {
  title: string;
  count: number;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardAction>
          <span className="text-sm text-muted-foreground tabular-nums">
            {count}
          </span>
        </CardAction>
      </CardHeader>
      <CardContent>
        {count === 0 ? (
          <p className="text-muted-foreground">{empty}</p>
        ) : (
          <ul className="divide-y">{children}</ul>
        )}
      </CardContent>
    </Card>
  );
}

// Each item links to the source panel showing where it came from.
function Item({
  href,
  title,
  detail,
  aside,
}: {
  href: string;
  title: React.ReactNode;
  detail?: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <li className="py-1 first:pt-0 last:pb-0">
      <Link
        href={href}
        scroll={false}
        className="-mx-2 flex items-start gap-3 rounded-md px-2 py-1.5 outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="min-w-0 flex-1">
          <p className="font-medium">{title}</p>
          {detail && <p className="text-muted-foreground">{detail}</p>}
        </div>
        {aside && (
          <div className="flex shrink-0 items-center gap-1.5">{aside}</div>
        )}
      </Link>
    </li>
  );
}

function SourceCount({
  sources,
  documents,
}: {
  sources: Source[];
  documents: Documents;
}) {
  const names = sources
    .map((source) => documents.get(source.document_id)?.filename)
    .filter(Boolean)
    .join("\n");

  return (
    <span
      title={names}
      className="inline-flex items-center gap-1 text-xs text-muted-foreground tabular-nums"
    >
      <FileText className="size-3.5" aria-hidden />
      {sources.length}
      <span className="sr-only">
        {sources.length === 1 ? "source document" : "source documents"}
      </span>
    </span>
  );
}

function joinDefined(...parts: (string | null | undefined)[]) {
  return parts.filter(Boolean).join(" · ") || null;
}

// Pairs each item with its position in the API array, which links refer to.
function withIndex<T>(items: T[]): [T, number][] {
  return items.map((item, index) => [item, index]);
}

const MEDICATION_ORDER = { active: 0, changed: 1, unknown: 2, stopped: 3 };

export function Medications({
  items,
  documents,
}: {
  items: Medication[];
  documents: Documents;
}) {
  const sorted = withIndex(items).sort(
    ([a], [b]) =>
      MEDICATION_ORDER[a.status ?? "unknown"] -
      MEDICATION_ORDER[b.status ?? "unknown"],
  );

  return (
    <Section
      title="Medications"
      count={items.length}
      empty="No medications found in your documents."
    >
      {sorted.map(([med, index]) => (
        <Item
          key={index}
          href={itemHref("medications", index)}
          title={
            <span
              className={
                med.status === "stopped"
                  ? "text-muted-foreground line-through decoration-muted-foreground/50"
                  : undefined
              }
            >
              {med.name}
            </span>
          }
          detail={joinDefined(
            med.dose,
            med.route,
            med.frequency,
            med.status === "stopped" && med.stop_date
              ? `stopped ${formatDate(med.stop_date)}`
              : null,
          )}
          aside={
            <>
              {med.status === "stopped" && (
                <Badge variant="secondary">Stopped</Badge>
              )}
              {med.status === "changed" && (
                <Badge variant="outline">Changed</Badge>
              )}
              <SourceCount sources={med.sources} documents={documents} />
            </>
          }
        />
      ))}
    </Section>
  );
}

export function Allergies({
  items,
  documents,
}: {
  items: Allergy[];
  documents: Documents;
}) {
  return (
    <Section
      title="Allergies"
      count={items.length}
      empty="No allergies found in your documents."
    >
      {items.map((allergy, index) => (
        <Item
          key={index}
          href={itemHref("allergies", index)}
          title={allergy.substance}
          detail={allergy.reaction}
          aside={
            <>
              {allergy.severity === "severe" && (
                <Badge variant="destructive">Severe</Badge>
              )}
              {allergy.severity === "moderate" && (
                <Badge variant="outline">Moderate</Badge>
              )}
              {allergy.severity === "mild" && (
                <Badge variant="secondary">Mild</Badge>
              )}
              <SourceCount sources={allergy.sources} documents={documents} />
            </>
          }
        />
      ))}
    </Section>
  );
}

export function Conditions({
  items,
  documents,
}: {
  items: Condition[];
  documents: Documents;
}) {
  return (
    <Section
      title="Conditions"
      count={items.length}
      empty="No conditions found in your documents."
    >
      {items.map((condition, index) => (
        <Item
          key={index}
          href={itemHref("conditions", index)}
          title={condition.name}
          detail={
            condition.onset_date && `Since ${formatDate(condition.onset_date)}`
          }
          aside={
            <>
              {condition.status === "resolved" && (
                <Badge variant="secondary">Resolved</Badge>
              )}
              <SourceCount sources={condition.sources} documents={documents} />
            </>
          }
        />
      ))}
    </Section>
  );
}

export function Labs({
  items,
  documents,
}: {
  items: Lab[];
  documents: Documents;
}) {
  const sorted = withIndex(items).sort(([a], [b]) =>
    (b.date ?? "").localeCompare(a.date ?? ""),
  );

  return (
    <Section
      title="Lab results"
      count={items.length}
      empty="No lab results found in your documents."
    >
      {sorted.map(([lab, index]) => (
        <Item
          key={index}
          href={itemHref("labs", index)}
          title={lab.test}
          detail={joinDefined(
            lab.reference_range && `Range ${lab.reference_range}`,
            lab.date && formatDate(lab.date),
          )}
          aside={
            <>
              {lab.value !== null && (
                <span className="font-medium tabular-nums">
                  {lab.value} {lab.unit}
                </span>
              )}
              {lab.flag === "high" && <Badge variant="destructive">High</Badge>}
              {lab.flag === "low" && <Badge variant="destructive">Low</Badge>}
              <SourceCount sources={lab.sources} documents={documents} />
            </>
          }
        />
      ))}
    </Section>
  );
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <Section
      title="Timeline"
      count={events.length}
      empty="No dated events found in your documents."
    >
      {events.map((event) => (
        <li
          key={event.key}
          className="grid grid-cols-[6.5rem_1fr] gap-3 py-2.5 first:pt-0 last:pb-0"
        >
          <time
            dateTime={event.date}
            className="text-muted-foreground tabular-nums"
          >
            {formatDate(event.date)}
          </time>
          <div className="min-w-0">
            <p className="font-medium">{event.label}</p>
            {event.detail && (
              <p className="text-muted-foreground">{event.detail}</p>
            )}
          </div>
        </li>
      ))}
    </Section>
  );
}
