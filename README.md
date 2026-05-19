# multi-tenant-genie

A small, reusable demo that shows how to enforce **multi-tenant data isolation in Databricks Genie** using an **ABAC row filter** backed by a Unity Catalog ACL table.

The same Genie Space, the same underlying tables, the same SQL query — but each caller (service principal or user) only sees rows for the tenants they are mapped to in an ACL table. No prompt-engineering, no per-tenant Genie Spaces, no per-tenant schemas. Isolation is enforced at the storage layer.

Based on the pattern described in [Embedding Genie API for a Multi-Tenant Application](https://medium.com/dbsql-sme-engineering/embedding-genie-api-for-a-multi-tenant-application-d307bfbfc89b).

---

## What's in the repo

```
multi-tenant-genie/
├── notebooks/
│   ├── 01_setup.sql           Provision catalog/schema, tables, ACL, function, row filter
│   ├── 02_demo_row_filter.sql Live-demo the ACL → visibility behavior in SQL
│   └── 03_query_genie.py      Query a Genie Space via the Conversation API
└── genie/
    └── instructions.md        Paste these into your Genie Space "Instructions" panel
```

All notebooks accept widget parameters (`catalog`, `schema`) so the demo is reusable across workspaces and customers.

---

## Demo flow (10 minutes)

### 1. Run `01_setup.sql`

Creates the demo catalog/schema, the `customer_orders` fact table, the `tenant_acl` ACL table, the `filter_by_tenant` ABAC function, and applies the row filter to `customer_orders`.

Defaults: catalog `main`, schema `demo_abac`. Override with widgets.

### 2. Run `02_demo_row_filter.sql`

Walks through the "same query, different ACL, different rows" narrative:

1. No ACL row for me → `SELECT *` returns 0 rows.
2. Grant me one tenant → I see only that tenant's orders.
3. Grant me a second tenant → I see two tenants.
4. Revoke one → instant offboarding, no permission change.

This is the heart of the demo. Everything else just wraps it.

### 3. Create a Genie Space

Point the Genie Space at `<catalog>.<schema>.customer_orders`. Copy the contents of [`genie/instructions.md`](genie/instructions.md) into the Space's instructions panel.

The row filter is already on the table — Genie will inherit it automatically.

### 4. Run `03_query_genie.py`

Asks the Genie Space a question via the Conversation API and prints the SQL + results. Run it twice with different ACL state between runs to demonstrate that **the same Genie question returns different data depending on who's allowed to see what**.

---

## How the row filter actually works

```sql
CREATE OR REPLACE FUNCTION filter_by_tenant(tenant_id STRING)
RETURNS BOOLEAN
RETURN EXISTS (
  SELECT 1 FROM tenant_acl t
  WHERE t.tenant_id = tenant_id
    AND t.principal = current_user()
);

ALTER TABLE customer_orders SET ROW FILTER filter_by_tenant ON (tenant_id);
```

- Function is called **once per row**, with that row's `tenant_id` value passed as the parameter.
- Returns `true` if there exists an ACL row mapping `current_user()` (the caller) to that tenant.
- `tenant_acl` is a simple `(principal, tenant_id)` table — one row per (principal, tenant) it's allowed to see.
- A principal mapped to N tenants = N rows in `tenant_acl`. No schema change needed.

When Genie is invoked, `current_user()` resolves to whoever the Genie call authenticated as — typically the embedded app's service principal, or an end user under OBO auth. Either way, the row filter is the backstop.

---

## Requirements

- Unity Catalog enabled workspace
- Permission to create catalog/schema/tables/functions in the target catalog
- A SQL Warehouse (any size; serverless recommended)
- For `03_query_genie.py`: `databricks-sdk` in the notebook environment (preinstalled on most ML/standard DBR versions)

---

## License

MIT
