"use client";

import { UploadItem } from "@/lib/document";
import { useEffect, useRef, useState } from "react";
import Dropzone from "./dropzone";
import FileList from "./file-list";
import { processDocument } from "@/lib/processing";

export default function Uploader() {
  const [items, setItems] = useState<UploadItem[]>([]);
  const cancels = useRef<(() => void)[]>([]);

  useEffect(() => {
    const list = cancels.current;
    return () => list.forEach((c) => c());
  }, []);

  function onDrop(acceptedFiles: File[]) {
    const newItems: UploadItem[] = acceptedFiles.map((file) => ({
      id: crypto.randomUUID(),
      file,
      status: "queued",
    }));
    setItems((prevItems) => [...prevItems, ...newItems]);
    for (const item of newItems) {
      cancels.current.push(
        processDocument(item.file, (status, error) => {
          setItems((prev) =>
            prev.map((it) =>
              it.id === item.id ? { ...it, status, error } : it,
            ),
          );
        }),
      );
    }
  }

  return (
    <div className="space-y-4">
      <Dropzone onDrop={onDrop} />
      <FileList items={items} />
    </div>
  );
}
