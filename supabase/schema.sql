create table if not exists public.chatgpt_accounts (
    id text primary key,
    label text not null,
    account_id text not null,
    access_token_enc text not null,
    refresh_token_enc text not null,
    id_token_enc text,
    expires_at bigint not null,
    status text not null default 'active',
    last_error text,
    created_at bigint not null,
    updated_at bigint not null
);

create index if not exists chatgpt_accounts_status_idx
    on public.chatgpt_accounts (status);

create index if not exists chatgpt_accounts_expires_at_idx
    on public.chatgpt_accounts (expires_at);

create table if not exists public.device_login_sessions (
    id text primary key,
    device_auth_id text not null,
    user_code text not null,
    interval_seconds integer not null,
    expires_at bigint not null,
    status text not null default 'pending',
    created_at bigint not null,
    updated_at bigint not null
);

create index if not exists device_login_sessions_status_idx
    on public.device_login_sessions (status);

create index if not exists device_login_sessions_expires_at_idx
    on public.device_login_sessions (expires_at);

alter table public.chatgpt_accounts enable row level security;
alter table public.device_login_sessions enable row level security;
