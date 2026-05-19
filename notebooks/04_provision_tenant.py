# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Provision a tenant service principal and query Genie as that SP
# MAGIC
# MAGIC This notebook is the **realistic end-to-end** that a multi-tenant SaaS
# MAGIC app would automate at customer onboarding time, plus the request-time
# MAGIC code that mints a token and calls Genie as that tenant.
# MAGIC
# MAGIC **What it does:**
# MAGIC 1. Creates a workspace-level service principal for the tenant
# MAGIC 2. Generates an OAuth M2M client secret for that SP
# MAGIC 3. Grants the SP the minimum UC + warehouse + Genie permissions
# MAGIC 4. Inserts the `(principal, tenant_id)` ACL row
# MAGIC 5. Performs the OAuth client-credentials exchange to mint an access token
# MAGIC 6. Calls the Genie Space API **as the SP** and shows the filtered result
# MAGIC
# MAGIC **What's intentionally different from production:**
# MAGIC - We print the client secret in the notebook output. In production it's
# MAGIC   read once at provisioning time and stored in your secrets manager
# MAGIC   keyed by tenant_id; the runtime app fetches it from there.
# MAGIC - We grant via API in the same notebook. In production this lives in
# MAGIC   Terraform / a tenant-onboarding job.
# MAGIC
# MAGIC **Required identity to run:** workspace admin (you).
# MAGIC No account admin needed — workspace-level SPs + the workspace OAuth
# MAGIC token endpoint cover this whole flow.

# COMMAND ----------

# MAGIC %pip install --quiet --upgrade "databricks-sdk>=0.40"
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("catalog",   "fd_serverless_workspace_catalog", "Catalog")
dbutils.widgets.text("schema",    "demo_abac",                       "Schema")
dbutils.widgets.text("warehouse", "01c0302f2399224e",                "Warehouse ID")
dbutils.widgets.text("space_id",  "01f1538ad39d1dbc89bdd9f93ab3d3cc","Genie Space ID")
dbutils.widgets.text("tenant_id", "acme",                            "Tenant ID to provision for")

CATALOG   = dbutils.widgets.get("catalog")
SCHEMA    = dbutils.widgets.get("schema")
WAREHOUSE = dbutils.widgets.get("warehouse")
SPACE     = dbutils.widgets.get("space_id")
TENANT    = dbutils.widgets.get("tenant_id")
SP_NAME   = f"mt-genie-tenant-{TENANT}"

print(f"Provisioning SP {SP_NAME} for tenant '{TENANT}'")
print(f"Targets: catalog={CATALOG} schema={SCHEMA} warehouse={WAREHOUSE} space={SPACE}")

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
import time

w = WorkspaceClient()
host = w.config.host.rstrip("/")
print(f"Workspace: {host}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## STEP 1 — Create the service principal
# MAGIC Idempotent: if an SP with this display name already exists, delete it
# MAGIC first. (In production you'd skip the delete and treat the existing SP
# MAGIC as a no-op or a re-onboarding case.)

# COMMAND ----------

for existing in w.service_principals.list(filter=f"displayName eq '{SP_NAME}'"):
    print(f"  deleting pre-existing SP id={existing.id}")
    w.service_principals.delete(id=existing.id)

sp = w.service_principals.create(display_name=SP_NAME, active=True)
print(f"Created SP")
print(f"  id (database)      : {sp.id}")
print(f"  application_id     : {sp.application_id}   ← this is the OAuth client_id")

# COMMAND ----------

# MAGIC %md
# MAGIC ## STEP 2 — Generate an OAuth M2M client secret
# MAGIC The secret is returned **once**. In production, your provisioning job
# MAGIC writes it straight into your secrets manager keyed by `tenant_id`.

# COMMAND ----------

sec = w.service_principal_secrets_proxy.create(service_principal_id=str(sp.id))
CLIENT_ID     = sp.application_id
CLIENT_SECRET = sec.secret

print(f"Secret minted (id={sec.id}, status={sec.status})")
print()
print(f"  CLIENT_ID     = {CLIENT_ID}")
print(f"  CLIENT_SECRET = {CLIENT_SECRET}")
print()
print("⚠️  In production, save (CLIENT_ID, CLIENT_SECRET) to your secrets")
print("   manager NOW, keyed by tenant_id. The secret is unrecoverable.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## STEP 3 — Grant the SP the minimum permissions
# MAGIC - `USE_CATALOG` on the catalog
# MAGIC - `USE_SCHEMA` on the schema
# MAGIC - `SELECT` on `customer_orders` (the fact table — has the row filter)
# MAGIC - `SELECT` on `tenant_acl`        (the row filter reads it via EXISTS)
# MAGIC - `EXECUTE` on the row filter function
# MAGIC - `CAN_USE` on the SQL warehouse
# MAGIC - `CAN_RUN` on the Genie Space
# MAGIC
# MAGIC No `INSERT/UPDATE/DELETE` anywhere — the tenant should not be able to
# MAGIC mutate its own ACL, only the row filter reads it.

# COMMAND ----------

def uc_grant(sec_type: str, name: str, perms: list[str]):
    w.api_client.do(
        "PATCH",
        f"/api/2.1/unity-catalog/permissions/{sec_type}/{name}",
        body={"changes": [{"principal": CLIENT_ID, "add": perms}]},
    )
    print(f"  + {perms} on {sec_type}={name}")

uc_grant("catalog",  CATALOG,                                         ["USE_CATALOG"])
uc_grant("schema",   f"{CATALOG}.{SCHEMA}",                           ["USE_SCHEMA"])
uc_grant("table",    f"{CATALOG}.{SCHEMA}.customer_orders",           ["SELECT"])
uc_grant("table",    f"{CATALOG}.{SCHEMA}.tenant_acl",                ["SELECT"])
uc_grant("function", f"{CATALOG}.{SCHEMA}.filter_by_tenant",          ["EXECUTE"])

print()
print("Warehouse CAN_USE...")
w.api_client.do(
    "PATCH",
    f"/api/2.0/permissions/warehouses/{WAREHOUSE}",
    body={"access_control_list": [
        {"service_principal_name": CLIENT_ID, "permission_level": "CAN_USE"}
    ]},
)
print("  + CAN_USE on warehouse")

print("\nGenie Space CAN_RUN...")
w.api_client.do(
    "PATCH",
    f"/api/2.0/permissions/genie/{SPACE}",
    body={"access_control_list": [
        {"service_principal_name": CLIENT_ID, "permission_level": "CAN_RUN"}
    ]},
)
print("  + CAN_RUN on Genie Space")

# COMMAND ----------

# MAGIC %md
# MAGIC ## STEP 4 — Insert the ACL row
# MAGIC One row per (tenant, SP) pair. If the same tenant is co-owned by
# MAGIC multiple SPs, insert multiple rows. If the same SP needs multiple
# MAGIC tenants, insert multiple rows.

# COMMAND ----------

def run_sql(sql: str):
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=WAREHOUSE, wait_timeout="30s",
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(0.3)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error.message if r.status.error else r.status.state)
    return r.result.data_array if r.result else None

run_sql(f"DELETE FROM {CATALOG}.{SCHEMA}.tenant_acl WHERE principal = '{CLIENT_ID}'")
run_sql(f"INSERT INTO {CATALOG}.{SCHEMA}.tenant_acl VALUES ('{CLIENT_ID}', '{TENANT}')")
print(f"ACL row inserted: ('{CLIENT_ID}', '{TENANT}')")

print("\nCurrent tenant_acl state:")
for row in (run_sql(f"SELECT * FROM {CATALOG}.{SCHEMA}.tenant_acl ORDER BY tenant_id") or []):
    print(f"  {row}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## STEP 5 — Mint an OAuth M2M access token
# MAGIC This is the code that lives in your runtime app: take the tenant's
# MAGIC `(client_id, client_secret)` from your secrets manager and exchange
# MAGIC them for a workspace access token.
# MAGIC
# MAGIC **Workspace-level endpoint:** `POST <host>/oidc/v1/token`
# MAGIC **Account-level endpoint:**   `POST https://accounts.cloud.databricks.com/oidc/accounts/<account_id>/v1/token`
# MAGIC
# MAGIC Use whichever matches your SP scope. Workspace SPs use the workspace
# MAGIC endpoint.

# COMMAND ----------

import requests

resp = requests.post(
    f"{host}/oidc/v1/token",
    auth=(CLIENT_ID, CLIENT_SECRET),
    data={"grant_type": "client_credentials", "scope": "all-apis"},
    timeout=20,
)
resp.raise_for_status()
ACCESS_TOKEN = resp.json()["access_token"]
print(f"Got access token (length {len(ACCESS_TOKEN)})")
print(f"  expires_in : {resp.json().get('expires_in')}s")
print(f"  token_type : {resp.json().get('token_type')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## STEP 6 — Call Genie as the tenant SP
# MAGIC This is the request-time code. Use the SP's bearer token; everything
# MAGIC else is identical to calling Genie as a user.
# MAGIC
# MAGIC **The key moment:** the SQL the LLM generates is run as the SP, so
# MAGIC `current_user()` inside the row filter resolves to this SP's
# MAGIC application_id, the ACL only has one tenant mapped, and the result
# MAGIC physically cannot include any other tenant's rows.

# COMMAND ----------

H = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

print(f"Asking Genie as SP for tenant '{TENANT}'...")
r1 = requests.post(
    f"{host}/api/2.0/genie/spaces/{SPACE}/start-conversation",
    headers=H,
    json={"content": "What is the total revenue by tenant?"},
    timeout=30,
)
r1.raise_for_status()
conv = r1.json()["conversation_id"]
mid  = r1.json()["message_id"]
print(f"  conversation_id={conv} message_id={mid}")

print("Polling for completion...")
for _ in range(60):
    rs = requests.get(
        f"{host}/api/2.0/genie/spaces/{SPACE}/conversations/{conv}/messages/{mid}",
        headers=H, timeout=20,
    )
    rs.raise_for_status()
    msg = rs.json()
    if msg.get("status") in ("COMPLETED", "FAILED", "ERROR", "CANCELLED"):
        break
    time.sleep(2)

print(f"Final status: {msg.get('status')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## STEP 7 — Show the SQL Genie generated, and the rows it returned
# MAGIC The SQL has no tenant filter in it (the LLM doesn't know about
# MAGIC tenants). The row filter on the table is what restricts the result.

# COMMAND ----------

import pandas as pd

for att in msg.get("attachments", []):
    if att.get("query"):
        print("Generated SQL:")
        print(att["query"]["query"])
        print()
        rq = requests.get(
            f"{host}/api/2.0/genie/spaces/{SPACE}/conversations/{conv}"
            f"/messages/{mid}/attachments/{att['attachment_id']}/query-result",
            headers=H, timeout=30,
        )
        rq.raise_for_status()
        sr = rq.json().get("statement_response", {})
        if "result" in sr and sr["result"].get("data_array") is not None:
            cols = [c["name"] for c in sr["manifest"]["schema"]["columns"]]
            display(pd.DataFrame(sr["result"]["data_array"], columns=cols))
        else:
            print("(no tabular result)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Compare: ask the same question as YOU (the workspace user)
# MAGIC With your current ACL state, you should see whatever you've granted
# MAGIC yourself in `02_demo_row_filter.sql`. The SP above can only ever see
# MAGIC its one tenant.

# COMMAND ----------

from datetime import timedelta

me_resp = w.genie.start_conversation_and_wait(
    space_id=SPACE,
    content="What is the total revenue by tenant?",
    timeout=timedelta(seconds=180),
)
for att in me_resp.attachments or []:
    if att.query is not None:
        qr = w.genie.get_message_attachment_query_result(
            space_id=SPACE, conversation_id=me_resp.conversation_id,
            message_id=me_resp.id, attachment_id=att.attachment_id,
        )
        sr = qr.statement_response
        cols = [c.name for c in sr.manifest.schema.columns]
        print(f"As {w.current_user.me().user_name}:")
        display(pd.DataFrame(sr.result.data_array or [], columns=cols))
        break

# COMMAND ----------

# MAGIC %md
# MAGIC ## What you just demonstrated
# MAGIC - Same Genie Space.
# MAGIC - Same natural-language question.
# MAGIC - Two different callers (one SP scoped to `acme`, one workspace user).
# MAGIC - Two different answers, enforced at the storage layer by the row filter.
# MAGIC
# MAGIC In a real SaaS app, the workspace user is replaced by your own app's
# MAGIC tenant context: your app already knows which customer is logged in, it
# MAGIC looks up that customer's `(client_id, client_secret)` from your secrets
# MAGIC manager, mints a token, and calls Genie. Customers physically cannot
# MAGIC see each other's data — not because the LLM is clever, but because the
# MAGIC database refuses to return the rows.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cleanup (optional)
# MAGIC Uncomment to remove the SP and its ACL row.

# COMMAND ----------

# w.service_principals.delete(id=sp.id)
# run_sql(f"DELETE FROM {CATALOG}.{SCHEMA}.tenant_acl WHERE principal = '{CLIENT_ID}'")
# print(f"Deleted SP {sp.id} and ACL row for {CLIENT_ID}")
