-- Keep the Finance company label cached on the eDoc user projection.
-- The backend has always written this field for login, approval routing and
-- company-disable cascades; older dedicated schemas omitted the column.

begin;

alter table public.users
  add column if not exists company_name text not null default '';

update public.users user_row
set company_name = company_row.name
from public.companies company_row
where company_row.id = user_row.company_id
  and user_row.company_name is distinct from company_row.name;

comment on column public.users.company_name is
  'Finance-owned company display-name cache; canonical identity remains users.company_id.';

commit;
