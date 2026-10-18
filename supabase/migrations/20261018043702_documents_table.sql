-- One row per uploaded document, written by the API with the secret key.
-- status follows the pipeline: queued -> reading -> extracting -> done (or failed).
create table public.documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  filename text not null,
  content_type text not null,
  storage_path text not null,
  status text not null default 'queued'
    check (status in ('queued', 'reading', 'extracting', 'done', 'failed')),
  error text,
  file_hash text,
  pages jsonb,       -- [{number, width, height, needs_ocr, lines: [{id, page, text, bbox}]}]
  extraction jsonb,  -- ExtractionResult
  created_at timestamptz not null default now()
);

create index documents_user_id_created_at_idx
  on public.documents (user_id, created_at desc);

-- The publishable key can reach this table through the REST API, so lock it down.
-- The API uses the secret key and bypasses RLS.
alter table public.documents enable row level security;

create policy "Users read own document rows"
  on public.documents for select
  to authenticated
  using (user_id = (select auth.uid()));
