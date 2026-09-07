-- Production-safe bootstrap seed.
--
-- Reference configuration, roles, permissions, background job definitions and
-- internal notification defaults are versioned in migrations. People,
-- companies and organization data are projected from the Finance system after
-- deployment. Intentionally do not create demo users, sample documents,
-- trusted devices, credentials, certificates, notifications or exchange data
-- here.

select 1 as edoc_seed_is_intentionally_empty;
