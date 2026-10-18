"use client";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, DocumentPage, getPage, PageLine } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  CONFLICT_QUESTION,
  DOCUMENT_TYPE_LABEL,
  documentName,
  formatDate,
  HealthRecord,
  RecordDocument,
  Source,
} from "@/lib/record";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

// The open item lives in the URL (?item=medications.3) so the back button closes
// the panel and other parts of the app can link straight to an item's sources.
const ITEM_PARAM = "item";

const SECTIONS = ["medications", "allergies", "conditions", "labs"] as const;
type RecordSection = (typeof SECTIONS)[number];
export type ItemSection = RecordSection | "conflicts";

// Index into the API's array, not the display order: sections sort their items.
export function itemHref(section: ItemSection, index: number) {
  return `?${ITEM_PARAM}=${section}.${index}`;
}

// A conflict shows each side with the documents that say it; an item has one side.
type Side = { label: string | null; sources: Source[] };
type OpenItem = { title: string; description: string | null; sides: Side[] };

const ALLERGY_SIDE_LABEL: Record<string, string> = {
  Listed: "Lists this allergy",
  "Not listed": "Doesn't mention this allergy",
};

function findItem(record: HealthRecord, param: string | null): OpenItem | null {
  const [section, index] = param?.split(".") ?? [];
  if (section === "conflicts") {
    const conflict = record.conflicts[Number(index)];
    if (!conflict) return null;
    return {
      title: conflict.name,
      description: CONFLICT_QUESTION[conflict.kind],
      sides: conflict.variants.map(({ value, sources }) => ({
        label:
          conflict.kind === "allergy_missing"
            ? (ALLERGY_SIDE_LABEL[value] ?? value)
            : value,
        sources,
      })),
    };
  }
  if (!SECTIONS.includes(section as RecordSection)) return null;
  const item = record[section as RecordSection][Number(index)];
  if (!item) return null;
  const title =
    "substance" in item
      ? item.substance
      : "test" in item
        ? item.test
        : item.name;
  return {
    title,
    description: null,
    sides: [{ label: null, sources: item.sources }],
  };
}

type SourcePage = { number: number; lineIds: string[] };
type SourceGroup = { documentId: string; pages: SourcePage[] };

// Evidence ids look like "p2-L14": page 2, line 14.
function groupSources(sources: Source[]): SourceGroup[] {
  const byDocument = new Map<string, Map<number, string[]>>();
  for (const source of sources) {
    const pages = byDocument.get(source.document_id) ?? new Map();
    byDocument.set(source.document_id, pages);
    for (const lineId of source.evidence) {
      const page = Number(/^p(\d+)-L\d+$/.exec(lineId)?.[1]);
      if (page) pages.set(page, [...(pages.get(page) ?? []), lineId]);
    }
  }
  return [...byDocument].map(([documentId, pages]) => ({
    documentId,
    pages: [...pages]
      .sort(([a], [b]) => a - b)
      .map(([number, lineIds]) => ({ number, lineIds })),
  }));
}

export default function SourcePanel({
  record,
  documents,
}: {
  record: HealthRecord;
  documents: Map<string, RecordDocument>;
}) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const param = searchParams.get(ITEM_PARAM);
  const open = findItem(record, param) !== null;

  // Keep showing the last item while the panel animates closed.
  const [shownParam, setShownParam] = useState(param);
  if (open && param !== shownParam) {
    setShownParam(param);
  }
  const shown = findItem(record, shownParam);
  const sides = (shown?.sides ?? []).map((side) => ({
    label: side.label,
    groups: groupSources(side.sources),
  }));
  const documentCount = new Set(
    sides.flatMap((side) => side.groups.map((group) => group.documentId)),
  ).size;

  return (
    <Sheet
      open={open}
      onOpenChange={(open) => {
        if (!open) router.replace(pathname, { scroll: false });
      }}
    >
      <SheetContent className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
        <SheetHeader className="border-b pr-12">
          <SheetTitle>{shown?.title}</SheetTitle>
          <SheetDescription>
            {shown?.description ??
              (documentCount === 1
                ? "Found in 1 document"
                : `Found in ${documentCount} documents`)}
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-4">
          {sides.map((side, i) => (
            <div key={i} className="border-b last:border-b-0">
              {side.label && (
                <h3 className="pt-4 font-semibold">{side.label}</h3>
              )}
              <div className={cn("divide-y", side.label && "*:first:pt-2")}>
                {side.groups.map((group) => (
                  <SourceBlock
                    key={group.documentId}
                    group={group}
                    document={documents.get(group.documentId)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function SourceBlock({
  group,
  document,
}: {
  group: SourceGroup;
  document: RecordDocument | undefined;
}) {
  const meta = [
    document?.type ? DOCUMENT_TYPE_LABEL[document.type] : "Document",
    document?.date && formatDate(document.date),
    document?.provider && document.filename,
  ].filter(Boolean);

  return (
    <section className="space-y-3 py-4">
      <div>
        <p className="font-medium">{documentName(document)}</p>
        <p className="text-muted-foreground">{meta.join(" · ")}</p>
      </div>
      {group.pages.map((page) => (
        <PageStrip
          key={page.number}
          documentId={group.documentId}
          page={page}
          filename={document?.filename ?? "the document"}
        />
      ))}
    </section>
  );
}

// Page image URLs are signed for an hour; refetch a little before they expire.
const PAGE_TTL_MS = 50 * 60 * 1000;
const pageCache = new Map<
  string,
  { at: number; page: Promise<DocumentPage> }
>();

function loadPage(documentId: string, number: number) {
  const key = `${documentId}/${number}`;
  const cached = pageCache.get(key);
  if (cached && Date.now() - cached.at < PAGE_TTL_MS) return cached.page;
  const page = getPage(documentId, number);
  pageCache.set(key, { at: Date.now(), page });
  page.catch(() => pageCache.delete(key));
  return page;
}

type PageState =
  | { status: "loading" }
  | { status: "failed"; error: string }
  | { status: "loaded"; page: DocumentPage };

async function fetchPage(
  documentId: string,
  number: number,
): Promise<PageState> {
  try {
    return { status: "loaded", page: await loadPage(documentId, number) };
  } catch (error) {
    return {
      status: "failed",
      error:
        error instanceof ApiError
          ? error.message
          : "Couldn't load this page. Check your connection and try again.",
    };
  }
}

function PageStrip({
  documentId,
  page,
  filename,
}: {
  documentId: string;
  page: SourcePage;
  filename: string;
}) {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchPage(documentId, page.number).then((next) => {
      if (!cancelled) setState(next);
    });
    return () => {
      cancelled = true;
    };
  }, [documentId, page.number, attempt]);

  if (state.status === "loading") return <Skeleton className="h-28 w-full" />;

  if (state.status === "failed") {
    return (
      <div className="space-y-2 rounded-md border border-dashed p-3">
        <p className="text-destructive">{state.error}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setState({ status: "loading" });
            setAttempt((n) => n + 1);
          }}
        >
          Try again
        </Button>
      </div>
    );
  }

  const lines = state.page.lines.filter((line) =>
    page.lineIds.includes(line.id),
  );
  // Scanned pages have no line boxes: show the whole page without a highlight.
  const found = lines.length > 0;

  return (
    <div className="space-y-1.5">
      <PageImage
        page={state.page}
        lines={lines}
        cropped={found && !expanded}
        alt={
          found
            ? `Page ${page.number} of ${filename}, highlighting: ${lines
                .map((line) => `"${line.text}"`)
                .join(", ")}`
            : `Page ${page.number} of ${filename}`
        }
      />
      <div className="flex items-center justify-between gap-3 text-muted-foreground">
        <span>
          Page {page.number}
          {!found && " · couldn't find the exact line on this page"}
        </span>
        {found && (
          <Button
            variant="link"
            size="sm"
            className="h-auto px-0"
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded ? "Show less" : "Show full page"}
          </Button>
        )}
      </div>
    </div>
  );
}

// Space kept above and below the highlighted lines, in line heights.
const CONTEXT_LINES = 3;
// A strip zooms in on the highlighted lines but never shows less of the page's
// width than this, so short lines keep some of their surroundings.
const MIN_STRIP_WIDTH = 0.6;

type Crop = { left: number; top: number; width: number; height: number };

// The part of the page around the highlighted lines, in image pixels.
function cropAround(page: DocumentPage, lines: PageLine[]): Crop {
  const lineHeight = Math.max(
    ...lines.map(({ bbox: [, y0, , y1] }) => y1 - y0),
  );
  const left = Math.max(
    0,
    Math.min(...lines.map(({ bbox }) => bbox[0])) - lineHeight,
  );
  const right = Math.min(
    page.width,
    Math.max(
      Math.max(...lines.map(({ bbox }) => bbox[2])) + lineHeight,
      left + MIN_STRIP_WIDTH * page.width,
    ),
  );
  const margin = CONTEXT_LINES * lineHeight;
  const top = Math.max(
    0,
    Math.min(...lines.map(({ bbox }) => bbox[1])) - margin,
  );
  const bottom = Math.min(
    page.height,
    Math.max(...lines.map(({ bbox }) => bbox[3])) + margin,
  );
  return { left, top, width: right - left, height: bottom - top };
}

function PageImage({
  page,
  lines,
  cropped,
  alt,
}: {
  page: DocumentPage;
  lines: PageLine[];
  cropped: boolean;
  alt: string;
}) {
  const crop = cropped
    ? cropAround(page, lines)
    : { left: 0, top: 0, width: page.width, height: page.height };
  const x = (value: number) => `${(value / crop.width) * 100}%`;
  const y = (value: number) => `${(value / crop.height) * 100}%`;

  // A ring, not a border: a border would shrink the box the percentages refer to.
  return (
    <div
      className="relative overflow-hidden rounded-md bg-white ring-1 ring-border"
      style={{ aspectRatio: `${crop.width} / ${crop.height}` }}
    >
      {/* Signed storage URLs expire, so they skip next/image's optimizer cache. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={page.image_url}
        alt={alt}
        className="absolute max-w-none"
        style={{
          left: x(-crop.left),
          top: y(-crop.top),
          width: x(page.width),
        }}
      />
      {lines.map((line) => {
        const [x0, y0, x1, y1] = line.bbox;
        return (
          <div
            key={line.id}
            aria-hidden
            className="absolute rounded-sm bg-yellow-300/60 mix-blend-multiply ring-1 ring-yellow-500/70"
            style={{
              left: x(x0 - crop.left - 4),
              width: x(x1 - x0 + 8),
              top: y(y0 - crop.top - 2),
              height: y(y1 - y0 + 4),
            }}
          />
        );
      })}
    </div>
  );
}
