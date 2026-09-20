-- Scanner database, Row Level Security, and private PDF storage.
-- Designed for the managed OpenAI File Search MVP while retaining an optional
-- pgvector-backed document_chunks table for a later self-managed retrieval path.

begin;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create extension if not exists vector with schema extensions;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  file_name text not null check (char_length(file_name) between 1 and 255),
  storage_path text not null unique,
  file_size_bytes bigint not null default 0 check (file_size_bytes between 0 and 26214400),
  mime_type text not null default 'application/pdf' check (mime_type = 'application/pdf'),
  page_count integer check (page_count is null or page_count > 0),
  status text not null default 'processing' check (status in ('processing', 'ready', 'failed')),
  retrieval_id text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  document_id uuid not null references public.documents(id) on delete cascade,
  title text not null default 'New conversation' check (char_length(title) between 1 and 160),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null check (char_length(content) between 1 and 50000),
  source_pages integer[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists public.document_chunks (
  id bigint generated always as identity primary key,
  document_id uuid not null references public.documents(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  page_number integer not null check (page_number > 0),
  chunk_index integer not null check (chunk_index >= 0),
  chunk_text text not null check (char_length(chunk_text) > 0),
  embedding extensions.vector(1536),
  created_at timestamptz not null default now(),
  unique (document_id, page_number, chunk_index)
);

create index if not exists documents_user_created_idx
  on public.documents (user_id, created_at desc);
create index if not exists conversations_user_document_idx
  on public.conversations (user_id, document_id, created_at desc);
create index if not exists messages_conversation_created_idx
  on public.messages (conversation_id, created_at);
create index if not exists document_chunks_document_page_idx
  on public.document_chunks (document_id, page_number, chunk_index);

create or replace function private.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, full_name)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'full_name', '')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

revoke all on function private.handle_new_user() from public, anon, authenticated;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_user();

alter table public.profiles enable row level security;
alter table public.documents enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.document_chunks enable row level security;

revoke all on table public.profiles from anon, authenticated;
revoke all on table public.documents from anon, authenticated;
revoke all on table public.conversations from anon, authenticated;
revoke all on table public.messages from anon, authenticated;
revoke all on table public.document_chunks from anon, authenticated;

grant select, update on table public.profiles to authenticated;
grant select, insert, update, delete on table public.documents to authenticated;
grant select, insert, update, delete on table public.conversations to authenticated;
grant select, insert, delete on table public.messages to authenticated;
-- document_chunks stays server-only. The service role bypasses RLS.

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own
  on public.profiles for select
  to authenticated
  using ((select auth.uid()) = id);

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own
  on public.profiles for update
  to authenticated
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);

drop policy if exists documents_select_own on public.documents;
create policy documents_select_own
  on public.documents for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists documents_insert_own on public.documents;
create policy documents_insert_own
  on public.documents for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists documents_update_own on public.documents;
create policy documents_update_own
  on public.documents for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists documents_delete_own on public.documents;
create policy documents_delete_own
  on public.documents for delete
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists conversations_select_own on public.conversations;
create policy conversations_select_own
  on public.conversations for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.documents d
      where d.id = document_id and d.user_id = (select auth.uid())
    )
  );

drop policy if exists conversations_insert_own on public.conversations;
create policy conversations_insert_own
  on public.conversations for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.documents d
      where d.id = document_id and d.user_id = (select auth.uid())
    )
  );

drop policy if exists conversations_update_own on public.conversations;
create policy conversations_update_own
  on public.conversations for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.documents d
      where d.id = document_id and d.user_id = (select auth.uid())
    )
  );

drop policy if exists conversations_delete_own on public.conversations;
create policy conversations_delete_own
  on public.conversations for delete
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists messages_select_own on public.messages;
create policy messages_select_own
  on public.messages for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.conversations c
      where c.id = conversation_id and c.user_id = (select auth.uid())
    )
  );

drop policy if exists messages_insert_own on public.messages;
create policy messages_insert_own
  on public.messages for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.conversations c
      where c.id = conversation_id and c.user_id = (select auth.uid())
    )
  );

drop policy if exists messages_delete_own on public.messages;
create policy messages_delete_own
  on public.messages for delete
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.conversations c
      where c.id = conversation_id and c.user_id = (select auth.uid())
    )
  );

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('pdfs', 'pdfs', false, 26214400, array['application/pdf'])
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists pdfs_select_own on storage.objects;
create policy pdfs_select_own
  on storage.objects for select
  to authenticated
  using (
    bucket_id = 'pdfs'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists pdfs_insert_own on storage.objects;
create policy pdfs_insert_own
  on storage.objects for insert
  to authenticated
  with check (
    bucket_id = 'pdfs'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists pdfs_update_own on storage.objects;
create policy pdfs_update_own
  on storage.objects for update
  to authenticated
  using (
    bucket_id = 'pdfs'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  )
  with check (
    bucket_id = 'pdfs'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists pdfs_delete_own on storage.objects;
create policy pdfs_delete_own
  on storage.objects for delete
  to authenticated
  using (
    bucket_id = 'pdfs'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

commit;
