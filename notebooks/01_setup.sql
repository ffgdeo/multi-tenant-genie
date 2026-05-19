-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 01 — Setup: multi-tenant ABAC row filter
-- MAGIC
-- MAGIC Provisions the demo schema, fact table, ACL table, ABAC function, and applies
-- MAGIC the row filter to the fact table.
-- MAGIC
-- MAGIC **Parameters (notebook widgets):**
-- MAGIC - `catalog` — target catalog (default `main`)
-- MAGIC - `schema`  — target schema within that catalog (default `demo_abac`)

-- COMMAND ----------

-- MAGIC %python
-- MAGIC dbutils.widgets.text("catalog", "main", "Catalog")
-- MAGIC dbutils.widgets.text("schema",  "demo_abac", "Schema")

-- COMMAND ----------

-- MAGIC %python
-- MAGIC catalog = dbutils.widgets.get("catalog")
-- MAGIC schema  = dbutils.widgets.get("schema")
-- MAGIC spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
-- MAGIC spark.sql(f"CREATE SCHEMA  IF NOT EXISTS {catalog}.{schema}")
-- MAGIC spark.sql(f"USE {catalog}.{schema}")
-- MAGIC print(f"Using {catalog}.{schema}")

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 1. Fact table — `customer_orders`
-- MAGIC A simple multi-tenant orders table. The `tenant_id` column is what the row
-- MAGIC filter will key off of.

-- COMMAND ----------

CREATE OR REPLACE TABLE customer_orders (
  order_id   INT,
  tenant_id  STRING,
  customer   STRING,
  product    STRING,
  amount     DECIMAL(10,2),
  order_date DATE
);

INSERT INTO customer_orders VALUES
  (1,  'acme',    'Acme HQ',         'Widgets',    100.00, DATE '2026-01-15'),
  (2,  'acme',    'Acme West',       'Gizmos',     250.00, DATE '2026-01-22'),
  (3,  'acme',    'Acme East',       'Widgets',    175.50, DATE '2026-02-03'),
  (4,  'globex',  'Globex Corp',     'Sprockets',  500.00, DATE '2026-01-18'),
  (5,  'globex',  'Globex EU',       'Cogs',       300.00, DATE '2026-02-01'),
  (6,  'globex',  'Globex APAC',     'Sprockets',  425.75, DATE '2026-02-14'),
  (7,  'initech', 'Initech Ltd',     'Staplers',   175.00, DATE '2026-01-30'),
  (8,  'initech', 'Initech R&D',     'Printers',   650.00, DATE '2026-02-09'),
  (9,  'umbrella','Umbrella Corp',   'Vials',      999.99, DATE '2026-01-25'),
  (10, 'umbrella','Umbrella Labs',   'Beakers',    275.00, DATE '2026-02-11');

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 2. ACL table — `tenant_acl`
-- MAGIC Maps a principal (user email or service principal application ID) to the
-- MAGIC tenants it is allowed to see. A principal mapped to N tenants = N rows.

-- COMMAND ----------

CREATE OR REPLACE TABLE tenant_acl (
  principal STRING,
  tenant_id STRING
);

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 3. ABAC filter function
-- MAGIC Called per-row by the row filter. Returns `true` iff the caller has an ACL
-- MAGIC row mapping them to the row's `tenant_id`.

-- COMMAND ----------

-- MAGIC %python
-- MAGIC catalog = dbutils.widgets.get("catalog")
-- MAGIC schema  = dbutils.widgets.get("schema")
-- MAGIC spark.sql(f"""
-- MAGIC CREATE OR REPLACE FUNCTION {catalog}.{schema}.filter_by_tenant(tenant_id STRING)
-- MAGIC RETURNS BOOLEAN
-- MAGIC RETURN EXISTS (
-- MAGIC   SELECT 1 FROM {catalog}.{schema}.tenant_acl t
-- MAGIC   WHERE t.tenant_id = tenant_id
-- MAGIC     AND t.principal = current_user()
-- MAGIC )
-- MAGIC """)
-- MAGIC print("Function created.")

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 4. Apply the row filter
-- MAGIC The `ON (tenant_id)` clause says "pass each row's `tenant_id` column value to
-- MAGIC the function as the argument".

-- COMMAND ----------

-- MAGIC %python
-- MAGIC catalog = dbutils.widgets.get("catalog")
-- MAGIC schema  = dbutils.widgets.get("schema")
-- MAGIC spark.sql(f"""
-- MAGIC ALTER TABLE {catalog}.{schema}.customer_orders
-- MAGIC SET ROW FILTER {catalog}.{schema}.filter_by_tenant ON (tenant_id)
-- MAGIC """)
-- MAGIC print("Row filter applied.")

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 5. Verify setup
-- MAGIC With an empty `tenant_acl`, the filter should hide every row from everyone.

-- COMMAND ----------

SELECT COUNT(*) AS visible_rows FROM customer_orders;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC Expected: `0`. The fact table has 10 rows, but the ACL is empty so the filter
-- MAGIC returns `false` for every row. Next, run `02_demo_row_filter.sql`.
