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
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("space_id", "", "Genie Space ID")
dbutils.widgets.text("question", "What is the total revenue by tenant?", "Question")

space_id = dbutils.widgets.get("space_id").strip()
question = dbutils.widgets.get("question").strip()

if not space_id:
    raise ValueError("Set the `space_id` widget to your Genie Space's ID (see the URL of the space in the workspace UI).")

print(f"Space ID: {space_id}")
print(f"Question: {question}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Who is this query running as?
# MAGIC The Genie call will execute as the notebook's identity — that's what the
# MAGIC row filter compares against `tenant_acl.principal`.

# COMMAND ----------

me = spark.sql("SELECT current_user() AS me").collect()[0]["me"]
print(f"Running as: {me}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ask Genie
# MAGIC Uses the Conversation API via `databricks-sdk`. Polls until the message
# MAGIC is `COMPLETED`, then prints the generated SQL and the result.

# COMMAND ----------

import time
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()


def ask_genie(space_id: str, question: str, conversation_id: str | None = None, timeout_s: int = 120):
    """Ask Genie a question. Returns (message, query_result | None)."""
    if conversation_id is None:
        started = w.genie.start_conversation_and_wait(
            space_id=space_id,
            content=question,
            timeout=__import__("datetime").timedelta(seconds=timeout_s),
        )
        message = started.message
        conversation_id = started.conversation_id
    else:
        message = w.genie.create_message_and_wait(
            space_id=space_id,
            conversation_id=conversation_id,
            content=question,
            timeout=__import__("datetime").timedelta(seconds=timeout_s),
        )

    query_result = None
    if message.attachments:
        for att in message.attachments:
            if att.query is not None:
                try:
                    qr = w.genie.get_message_attachment_query_result(
                        space_id=space_id,
                        conversation_id=conversation_id,
                        message_id=message.id,
                        attachment_id=att.attachment_id,
                    )
                    query_result = qr.statement_response
                    break
                except Exception as e:
                    print(f"  (failed to fetch query result for attachment {att.attachment_id}: {e})")
    return message, query_result, conversation_id


message, query_result, conversation_id = ask_genie(space_id, question)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Show the generated SQL

# COMMAND ----------

sql_text = None
if message.attachments:
    for att in message.attachments:
        if att.query is not None:
            sql_text = att.query.query
            break

if sql_text:
    print("Generated SQL:\n")
    print(sql_text)
else:
    print("Genie did not produce SQL. Message text:\n")
    if message.attachments:
        for att in message.attachments:
            if att.text is not None:
                print(att.text.content)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Show the result rows
# MAGIC These are post-row-filter — only rows the current user's ACL allows are
# MAGIC included in Genie's answer.

# COMMAND ----------

if query_result and query_result.result and query_result.result.data_array is not None:
    columns = [c.name for c in query_result.manifest.schema.columns]
    rows = query_result.result.data_array
    import pandas as pd
    df = pd.DataFrame(rows, columns=columns)
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
