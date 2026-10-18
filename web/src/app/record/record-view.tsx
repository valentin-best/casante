"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getRecord } from "@/lib/api";
import { buildTimeline, HealthRecord } from "@/lib/record";
import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Conflicts } from "./conflicts";
import { Allergies, Conditions, Labs, Medications, Timeline } from "./sections";
import SourcePanel from "./source-panel";

type State =
  | { status: "loading" }
  | { status: "failed"; error: string }
  | { status: "loaded"; record: HealthRecord };

async function fetchRecord(): Promise<State> {
  try {
    return { status: "loaded", record: await getRecord() };
  } catch (error) {
    return {
      status: "failed",
      error:
        error instanceof ApiError
          ? error.message
          : "Couldn't reach the server. Check your connection and try again.",
    };
  }
}

export default function RecordView() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchRecord().then((next) => {
      if (!cancelled) setState(next);
    });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (state.status === "loading") return <RecordSkeleton />;

  if (state.status === "failed") {
    return (
      <Card>
        <CardContent className="space-y-3">
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
        </CardContent>
      </Card>
    );
  }

  if (state.record.documents.length === 0) return <EmptyRecord />;

  return <Record record={state.record} />;
}

function Record({ record }: { record: HealthRecord }) {
  const documents = useMemo(
    () => new Map(record.documents.map((doc) => [doc.id, doc])),
    [record.documents],
  );
  const timeline = useMemo(() => buildTimeline(record), [record]);
  const count = record.documents.length;

  return (
    <div className="space-y-4">
      <Conflicts conflicts={record.conflicts} documents={documents} />
      <p className="text-sm text-muted-foreground">
        Built from {count} {count === 1 ? "document" : "documents"}. The icon
        next to each item shows how many documents mention it. Select an item to
        see where it came from.
      </p>
      <div className="grid items-start gap-4 lg:grid-cols-[3fr_2fr]">
        <div className="space-y-4">
          {/* Allergies are safety-critical: first thing on small screens. */}
          <div className="lg:hidden">
            <Allergies items={record.allergies} documents={documents} />
          </div>
          <Medications items={record.medications} documents={documents} />
          <Labs items={record.labs} documents={documents} />
        </div>
        <div className="space-y-4">
          <div className="hidden lg:block">
            <Allergies items={record.allergies} documents={documents} />
          </div>
          <Conditions items={record.conditions} documents={documents} />
          <Timeline events={timeline} />
        </div>
      </div>
      {/* Reads the URL, so it can't be prerendered. */}
      <Suspense>
        <SourcePanel record={record} documents={documents} />
      </Suspense>
    </div>
  );
}

function EmptyRecord() {
  return (
    <Card>
      <CardContent className="space-y-3 py-6 text-center">
        <p className="font-medium">Your record is empty</p>
        <p className="text-muted-foreground">
          Upload a few documents and we&apos;ll build your record from them.
        </p>
        <Button asChild size="sm">
          <Link href="/">Upload documents</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function SkeletonCard({ rows }: { rows: number }) {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-28" />
      </CardHeader>
      <CardContent className="space-y-3">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="space-y-1.5">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="h-3.5 w-3/5" />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function RecordSkeleton() {
  return (
    <div
      aria-busy
      aria-label="Loading your record"
      className="grid items-start gap-4 lg:grid-cols-[3fr_2fr]"
    >
      <div className="space-y-4">
        <SkeletonCard rows={4} />
        <SkeletonCard rows={3} />
      </div>
      <div className="space-y-4">
        <SkeletonCard rows={2} />
        <SkeletonCard rows={2} />
      </div>
    </div>
  );
}
