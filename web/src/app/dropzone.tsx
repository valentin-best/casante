"use client";

import { cn } from "@/lib/utils";
import { Upload } from "lucide-react";
import { useDropzone } from "react-dropzone";

export default function Dropzone({
  onDrop,
}: {
  onDrop: (files: File[]) => void;
}) {
  const { getRootProps, getInputProps, isDragActive, fileRejections } =
    useDropzone({
      onDrop,
      accept: {
        "application/pdf": [".pdf"],
        "image/jpeg": [".jpg", ".jpeg"],
        "image/png": [".png"],
      },
      maxSize: 10 * 1024 * 1024,
      multiple: true,
    });

  return (
    <div className="space-y-2">
      <div
        {...getRootProps()}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed border-muted-foreground/30 p-10 text-center transition-colors hover:bg-muted/50",
          isDragActive && "border-primary bg-primary/5",
        )}
      >
        <input {...getInputProps()} />
        <Upload className="size-6 text-muted-foreground" />
        <p className="font-medium">
          Drop medical documents here, or click to browse
        </p>
        <p className="text-sm text-muted-foreground">
          PDF, JPG or PNG · up to 10 MB
        </p>
      </div>
      {fileRejections.map(({ file, errors }, i) => (
        <p key={file.name + i} className="text-sm text-destructive">
          {file.name}: {errors[0].message}
        </p>
      ))}
    </div>
  );
}
