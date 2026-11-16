-- A fixture for tests/infra/compose-up.test.ts only: mounted with the shipped migrations over
-- /app/migrations, it shows that a second `up` runs the migrate service again and applies a new
-- file. It is never in migrations/ and never shipped.
CREATE TABLE infra_fixture (id integer PRIMARY KEY);
