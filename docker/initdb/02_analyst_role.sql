-- Model-written SQL runs as this role: SELECT only, read-only, time-limited.
CREATE ROLE analyst_ro LOGIN PASSWORD 'analyst_ro' CONNECTION LIMIT 8;  -- local dev only
ALTER ROLE analyst_ro SET default_transaction_read_only = on;
ALTER ROLE analyst_ro SET statement_timeout = '30s';
ALTER ROLE analyst_ro SET idle_in_transaction_session_timeout = '60s';

\connect bird
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE bird FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst_ro;
-- The dump is loaded after initdb runs; cover tables created later.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO analyst_ro;
