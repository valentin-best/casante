import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Conflict,
  CONFLICT_QUESTION,
  documentName,
  formatDate,
  joinNames,
  RecordDocument,
  Source,
} from "@/lib/record";
import { MessageCircleQuestion } from "lucide-react";
import Link from "next/link";
import { itemHref } from "./source-panel";

type Documents = Map<string, RecordDocument>;

// Allergies left out by the same documents share one card, so a letter saying
// "No known allergies" reads as one question instead of one card per allergy.
type ConflictCard =
  | { type: "values"; index: number; conflict: Conflict }
  | {
      type: "allergies";
      documentIds: string[];
      allergies: { index: number; name: string }[];
    };

function buildCards(conflicts: Conflict[]): ConflictCard[] {
  const cards: ConflictCard[] = [];
  const allergyCards = new Map<
    string,
    Extract<ConflictCard, { type: "allergies" }>
  >();
  conflicts.forEach((conflict, index) => {
    if (conflict.kind !== "allergy_missing") {
      cards.push({ type: "values", index, conflict });
      return;
    }
    const missing = conflict.variants.find((v) => v.value === "Not listed");
    const documentIds = uniqueDocuments(missing?.sources ?? []);
    const key = [...documentIds].sort().join();
    let card = allergyCards.get(key);
    if (!card) {
      card = { type: "allergies", documentIds, allergies: [] };
      allergyCards.set(key, card);
      cards.push(card);
    }
    card.allergies.push({ index, name: conflict.name });
  });
  return cards;
}

function uniqueDocuments(sources: Source[]) {
  return [...new Set(sources.map((source) => source.document_id))];
}

// "Dr. E. Rossi (30 Sept 2026) and Oakwood Specialty Clinic (14 Oct 2026)"
function namedDocuments(documentIds: string[], documents: Documents) {
  return joinNames(
    documentIds.map((id) => {
      const doc = documents.get(id);
      const name = documentName(doc);
      return doc?.date ? `${name} (${formatDate(doc.date)})` : name;
    }),
  );
}

export function Conflicts({
  conflicts,
  documents,
}: {
  conflicts: Conflict[];
  documents: Documents;
}) {
  const cards = buildCards(conflicts);
  if (cards.length === 0) return null;

  return (
    <section className="space-y-3">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Questions for your doctor</h2>
        <p className="text-muted-foreground">
          Your documents don&apos;t all say the same thing. We can&apos;t tell
          which one is right, so it&apos;s worth asking.
        </p>
      </div>
      <div className="grid items-start gap-4 md:grid-cols-2">
        {cards.map((card) =>
          card.type === "values" ? (
            <ValuesCard
              key={card.index}
              index={card.index}
              conflict={card.conflict}
              documents={documents}
            />
          ) : (
            <AllergiesCard
              key={`allergies-${card.allergies[0].index}`}
              card={card}
              documents={documents}
            />
          ),
        )}
      </div>
    </section>
  );
}

function Question({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 font-medium">
      <MessageCircleQuestion
        className="mt-0.5 size-4 shrink-0 text-muted-foreground"
        aria-hidden
      />
      {children}
    </p>
  );
}

// Every side gets the same styling: the app never marks one as right.
function ValuesCard({
  index,
  conflict,
  documents,
}: {
  index: number;
  conflict: Conflict;
  documents: Documents;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{conflict.name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-2.5">
          {conflict.variants.map((variant, i) => (
            <li key={i}>
              <p className="font-medium">{variant.value}</p>
              <p className="text-muted-foreground">
                {namedDocuments(uniqueDocuments(variant.sources), documents)}
              </p>
            </li>
          ))}
        </ul>
        <Question>{CONFLICT_QUESTION[conflict.kind]}</Question>
      </CardContent>
      <CardFooter className="border-t py-3">
        <Button asChild variant="outline" size="sm">
          <Link href={itemHref("conflicts", index)} scroll={false}>
            Compare sources
          </Link>
        </Button>
      </CardFooter>
    </Card>
  );
}

function AllergiesCard({
  card,
  documents,
}: {
  card: Extract<ConflictCard, { type: "allergies" }>;
  documents: Documents;
}) {
  const one = card.allergies.length === 1;
  const plural = card.documentIds.length > 1;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {one
            ? `${card.allergies[0].name} allergy`
            : `${card.allergies.length} allergies`}{" "}
          not on every document
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-muted-foreground">
          {namedDocuments(card.documentIds, documents)}{" "}
          {plural ? "don't" : "doesn't"} mention{" "}
          {one ? "this allergy" : "these allergies"}, but other documents list{" "}
          {one ? "it" : "them"}.
        </p>
        <ul className="flex flex-wrap gap-2" aria-label="Compare sources">
          {card.allergies.map((allergy) => (
            <li key={allergy.index}>
              <Button asChild variant="outline" size="sm">
                <Link
                  href={itemHref("conflicts", allergy.index)}
                  scroll={false}
                >
                  {allergy.name}
                </Link>
              </Button>
            </li>
          ))}
        </ul>
        <Question>
          {one
            ? CONFLICT_QUESTION.allergy_missing
            : "Ask that they're on file everywhere."}
        </Question>
      </CardContent>
    </Card>
  );
}
