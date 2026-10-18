import { DocumentStatus } from "./document";
import { createClient } from "./supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL!;

export type ApiDocument = {
  id: string;
  filename: string;
  content_type: string;
  status: DocumentStatus;
  error: string | null;
  created_at: string;
};

export class ApiError extends Error {}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { data } = await createClient().auth.getSession();
  const token = data.session?.access_token;

  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...init.headers,
      ...(token && { Authorization: `Bearer ${token}` }),
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      typeof body?.detail === "string"
        ? body.detail
        : "Something went wrong. Please try again.",
    );
  }
  return response.json();
}

export function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<ApiDocument>("/documents", { method: "POST", body: form });
}

export function startProcessing(id: string) {
  return request<ApiDocument>(`/documents/${id}/process`, { method: "POST" });
}

export function getDocument(id: string) {
  return request<ApiDocument>(`/documents/${id}`);
}
