import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  DocumentStatus,
  STATUS_LABEL,
  STATUS_PROGRESS,
  UploadItem,
} from "@/lib/document";
import { LoaderCircle } from "lucide-react";

function formatSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function badgeVariant(status: DocumentStatus) {
  if (status === "failed") return "destructive";
  if (status === "queued") return "secondary";
  return "default";
}

export default function FileList({ items }: { items: UploadItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No documents yet.</p>;
  }

  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.id} className="rounded-md border p-3">
          <div className="flex items-center gap-3">
            <span className="truncate font-medium">{item.file.name}</span>
            <span className="shrink-0 text-sm text-muted-foreground">
              {formatSize(item.file.size)}
            </span>
            <Badge variant={badgeVariant(item.status)} className="ml-auto">
              {(item.status === "reading" || item.status === "extracting") && (
                <LoaderCircle className="animate-spin" />
              )}
              {STATUS_LABEL[item.status]}
            </Badge>
          </div>
          <Progress
            value={STATUS_PROGRESS[item.status]}
            className={
              item.status === "failed"
                ? "mt-2 *:data-[slot=progress-indicator]:bg-destructive"
                : "mt-2"
            }
          />
          {item.status === "failed" && (
            <p className="mt-1 text-sm text-destructive">
              {item.error ?? "We couldn't process this document."}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
