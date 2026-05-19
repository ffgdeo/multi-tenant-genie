-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 02 — Live demo: ACL changes drive row visibility
-- MAGIC
-- MAGIC Run each cell with the customer watching. The query (`SELECT * FROM
-- MAGIC customer_orders`) **never changes** — only the ACL data does. That's the
-- MAGIC whole point: isolation lives in the data layer, not in the query.
-- MAGIC
-- MAGIC Prereq: `01_setup.sql` has been run with the same `catalog`/`schema`.

-- COMMAND ----------

-- MAGIC %python
-- MAGIC dbutils.widgets.text("catalog", "main", "Catalog")
-- MAGIC dbutils.widgets.text("schema",  "demo_abac", "Schema")
-- MAGIC catalog = dbutils.widgets.get("catalog")
-- MAGIC schema  = dbutils.widgets.get("schema")
-- MAGIC spark.sql(f"USE {catalog}.{schema}")
-- MAGIC print(f"Using {catalog}.{schema}")

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Who am I?
-- MAGIC `current_user()` is what the filter compares against `tenant_acl.principal`.

-- COMMAND ----------

SELECT current_user() AS me;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## STEP 1 — No ACL row for me yet
-- MAGIC Expect zero rows. The filter denies by default.

-- COMMAND ----------

SELECT * FROM customer_orders ORDER BY order_id;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## STEP 2 — Grant myself `acme` only

-- COMMAND ----------

INSERT INTO tenant_acl VALUES (current_user(), 'acme');

SELECT * FROM customer_orders ORDER BY order_id;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC Expected: 3 Acme rows.

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## STEP 3 — Add `globex` too (one principal, multiple tenants)

-- COMMAND ----------

INSERT INTO tenant_acl VALUES (current_user(), 'globex');

SELECT * FROM customer_orders ORDER BY order_id;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC Expected: 6 rows (3 Acme + 3 Globex). `initech` and `umbrella` still hidden.

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## STEP 4 — Revoke `acme` (instant offboarding)

-- COMMAND ----------

DELETE FROM tenant_acl WHERE principal = current_user() AND tenant_id = 'acme';

SELECT * FROM customer_orders ORDER BY order_id;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC Expected: 3 Globex rows. No permission change, no table rewrite — just an ACL
-- MAGIC row deletion.

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## STEP 5 — A different principal's mapping doesn't affect me

-- COMMAND ----------

INSERT INTO tenant_acl VALUES ('app-sp-initech@databricks.com', 'initech');

SELECT * FROM customer_orders ORDER BY order_id;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC Expected: still 3 Globex rows. The `initech` mapping belongs to a different
-- MAGIC principal (`app-sp-initech@...`), so it doesn't grant *me* anything. This is
-- MAGIC the multi-tenant guarantee: ACL rows are scoped to a specific identity.

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Reset (optional)
-- MAGIC Uncomment to wipe ACL state and start fresh.

-- COMMAND ----------

-- TRUNCATE TABLE tenant_acl;
