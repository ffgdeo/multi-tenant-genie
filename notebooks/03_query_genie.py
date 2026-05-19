# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Query the Genie Space via the Conversation API
# MAGIC
# MAGIC Asks a natural-language question to a Genie Space pointed at
# MAGIC `<catalog>.<schema>.customer_orders` (the table with the ABAC row filter).
# MAGIC
# MAGIC Because the row filter lives on the table, **Genie inherits the filter
# MAGIC automatically**. Same Genie Space, same question — but the answer depends
# MAGIC on the caller's ACL mappings.
# MAGIC
# MAGIC Run this notebook, then go to `02_demo_row_filter.sql` and add/remove a
# MAGIC row in `tenant_acl`, then re-run this notebook — watch the answer change.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Install a recent databricks-sdk
# MAGIC The default runtime SDK predates `w.genie`. Upgrade and restart Python.

# COMMAND ----------

# MAGIC %pip install --quiet --upgrade "databricks-sdk>=0.40"
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("space_id", "", "Genie Space ID")
dbutils.widgets.text("question", "What is the total revenue by tenant?", "Question")

space_id = dbutils.widgets.get("space_id").strip()
question = dbutils.widgets.get("question").strip()

if not space_id:
    raise ValueError(
        "Set the `space_id` widget to your Genie Space's ID. "
        "Find it in the URL of the space in the workspace UI: "
        "https://<workspace>/genie/rooms/<space_id>"
    )

print(f"Space ID: {space_id}")
print(f"Question: {question}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Who is this query running as?
# MAGIC The Genie call executes as the notebook's identity — that's what the
# MAGIC row filter compares against `tenant_acl.principal`.

# COMMAND ----------

me = spark.sql("SELECT current_user() AS me").collect()[0]["me"]
print(f"Running as: {me}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ask Genie
# MAGIC `start_conversation_and_wait` returns the completed `GenieMessage`
# MAGIC directly. The message carries its own `conversation_id`, so we don't
# MAGIC need a wrapper.

# COMMAND ----------

from datetime import timedelta
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()


def ask_genie(space_id: str, question: str, timeout_s: int = 180):
    """Ask Genie a fresh question. Returns (sql_text, columns, rows, message)."""
    msg = w.genie.start_conversation_and_wait(
        space_id=space_id,
        content=question,
        timeout=timedelta(seconds=timeout_s),
    )
    sql_text, cols, rows = None, None, None
    if msg.attachments:
        for att in msg.attachments:
            if att.query is not None:
                sql_text = att.query.query
                qr = w.genie.get_message_attachment_query_result(
                    space_id=space_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg.id,
                    attachment_id=att.attachment_id,
                )
                if qr.statement_response and qr.statement_response.result:
                    cols = [c.name for c in qr.statement_response.manifest.schema.columns]
                    rows = qr.statement_response.result.data_array
                break
    return sql_text, cols, rows, msg


sql_text, cols, rows, msg = ask_genie(space_id, question)
print(f"Status: {msg.status}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Show the generated SQL

# COMMAND ----------

if sql_text:
    print(sql_text)
else:
    print("Genie did not produce SQL. Message text:\n")
    if msg.attachments:
        for att in msg.attachments:
            if att.text is not None:
                print(att.text.content)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Show the result rows
# MAGIC These are post-row-filter — only rows the current user's ACL allows are
# MAGIC included in Genie's answer.

# COMMAND ----------

if rows is not None and cols is not None:
    import pandas as pd
    df = pd.DataFrame(rows, columns=cols)
    display(df)
else:
    print("No tabular result (Genie may have responded with text only).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Try it
# MAGIC 1. Run this notebook with the ACL empty → expect 0 rows / "no data" answer.
# MAGIC 2. Go to `02_demo_row_filter.sql`, insert an ACL row for `current_user()` +
# MAGIC    `'acme'`, then re-run this notebook → expect only Acme totals.
# MAGIC 3. Add `'globex'`, re-run → both Acme and Globex appear.
# MAGIC
# MAGIC The Genie Space and the question are identical across runs. The data layer
# MAGIC enforces the isolation.
