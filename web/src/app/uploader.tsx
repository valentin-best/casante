"use client";

import { UploadItem } from "@/lib/document";
import { useEffect, useRef, useState } from "react";
import Dropzone from "./dropzone";
import FileList from "./file-list";
import { simulateProcessing } from "@/lib/mock-processing";

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
        simulateProcessing((status) => {
          setItems((prev) =>
            prev.map((it) => (it.id === item.id ? { ...it, status } : it)),
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
