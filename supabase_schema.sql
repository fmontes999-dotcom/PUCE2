alter table public.orders
    add column if not exists user_id uuid references auth.users(id) on delete cascade;

alter table public.orders enable row level security;

drop policy if exists "Users can view their own orders" on public.orders;
create policy "Users can view their own orders"
    on public.orders for select
    using (auth.uid() = user_id);

drop policy if exists "Users can insert their own orders" on public.orders;
create policy "Users can insert their own orders"
    on public.orders for insert
    with check (auth.uid() = user_id);

drop policy if exists "Users can update their own orders" on public.orders;
create policy "Users can update their own orders"
    on public.orders for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can delete their own orders" on public.orders;
create policy "Users can delete their own orders"
    on public.orders for delete
    using (auth.uid() = user_id);

-- Restaurantes por usuario
create table if not exists public.restaurants (
    id bigint generated always as identity primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    address text,
    created_at timestamptz not null default now()
);

alter table public.restaurants enable row level security;

drop policy if exists "Users manage their own restaurants" on public.restaurants;
create policy "Users manage their own restaurants"
    on public.restaurants for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- Alertas / notificaciones por usuario
create table if not exists public.alerts (
    id bigint generated always as identity primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null,
    message text not null,
    read boolean not null default false,
    created_at timestamptz not null default now()
);

alter table public.alerts enable row level security;

drop policy if exists "Users manage their own alerts" on public.alerts;
create policy "Users manage their own alerts"
    on public.alerts for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- Conexiones con plataformas de delivery (modo demo)
create table if not exists public.connections (
    user_id uuid not null references auth.users(id) on delete cascade,
    platform text not null,
    created_at timestamptz not null default now(),
    primary key (user_id, platform)
);

alter table public.connections enable row level security;

drop policy if exists "Users manage their own connections" on public.connections;
create policy "Users manage their own connections"
    on public.connections for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);
