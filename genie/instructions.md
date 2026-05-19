# Genie Space — Instructions

Copy the **General Instructions** block below into your Genie Space's
*Instructions* panel. The *SQL Examples* are optional but improve query
quality in the demo.

The Genie Space should be configured against the single table:

```
<catalog>.<schema>.customer_orders
```

(no need to add `tenant_acl` — Genie doesn't need to know about the ACL.
The row filter is transparent.)

---

## General Instructions

> You are a sales analytics assistant for a multi-tenant SaaS application.
> The `customer_orders` table contains orders from many tenants. Each row has
> a `tenant_id` column identifying which tenant the row belongs to.
>
> A row-level security filter is applied to this table, so you only ever see
> rows for tenants the current user is authorized to view. You do not need to
> add a `WHERE tenant_id = ...` filter for security — the platform handles it.
> You may still use `tenant_id` for grouping and aggregation.
>
> When asked about totals, revenue, or counts, group by `tenant_id` so the
> user can see which tenants are contributing. Order the result by the
> aggregated metric descending unless the user asks otherwise.
>
> Use simple, readable SQL. Prefer ANSI SQL date functions
> (`date_trunc`, `month()`, `year()`) when working with `order_date`.

---

## Sample Questions

Add these to the Genie Space's *Sample Questions* / *Suggested prompts*:

- What is the total revenue by tenant?
- How many orders did each tenant place this year?
- Which product generated the most revenue?
- Show me a breakdown of orders by month and tenant
- Which tenant has the highest average order value?

---

## SQL Examples (optional but recommended)

These help Genie pattern-match well on the demo data. Add each as a
"trusted query" with the matching natural-language label.

**Label:** Total revenue by tenant
```sql
SELECT
  tenant_id,
  ROUND(SUM(amount), 2) AS total_revenue,
  COUNT(*)              AS order_count
FROM customer_orders
GROUP BY tenant_id
ORDER BY total_revenue DESC;
```

**Label:** Orders by month and tenant
```sql
SELECT
  DATE_TRUNC('MONTH', order_date) AS month,
  tenant_id,
  COUNT(*)                        AS orders,
  ROUND(SUM(amount), 2)           AS revenue
FROM customer_orders
GROUP BY month, tenant_id
ORDER BY month, tenant_id;
```

**Label:** Top product by revenue
```sql
SELECT
  product,
  ROUND(SUM(amount), 2) AS revenue,
  COUNT(*)              AS order_count
FROM customer_orders
GROUP BY product
ORDER BY revenue DESC;
```
