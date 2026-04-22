-- Health check for image2excel SQLite database.
-- Usage:
-- sqlite3 "/Users/ai/Downloads/data/image2excel/app.db" < scripts/sql/health_check.sql

.headers on
.mode column

SELECT 'table_row_counts' AS section, '' AS detail, '' AS value;
SELECT 'daily_summaries' AS table_name, COUNT(*) AS row_count FROM daily_summaries
UNION ALL SELECT 'product_records', COUNT(*) FROM product_records
UNION ALL SELECT 'purchase_items', COUNT(*) FROM purchase_items
UNION ALL SELECT 'purchase_receipts', COUNT(*) FROM purchase_receipts
UNION ALL SELECT 'sales_items', COUNT(*) FROM sales_items
UNION ALL SELECT 'sales_receipts', COUNT(*) FROM sales_receipts;

SELECT 'purchase_total_by_biz_date' AS section, '' AS detail, '' AS value;
SELECT
  pi.last_saved_date AS biz_date,
  ROUND(COALESCE(SUM(pi.amount), 0), 2) AS purchase_total
FROM purchase_items pi
GROUP BY pi.last_saved_date
ORDER BY pi.last_saved_date DESC;

SELECT 'sales_total_by_biz_date' AS section, '' AS detail, '' AS value;
SELECT
  si.last_saved_date AS biz_date,
  ROUND(COALESCE(SUM(si.amount), 0), 2) AS revenue_total
FROM sales_items si
GROUP BY si.last_saved_date
ORDER BY si.last_saved_date DESC;

SELECT 'purchase_dedup_conflicts' AS section, '' AS detail, '' AS value;
SELECT dedup_key, COUNT(*) AS duplicate_count
FROM purchase_items
GROUP BY dedup_key
HAVING COUNT(*) > 1;

SELECT 'sales_dedup_conflicts' AS section, '' AS detail, '' AS value;
SELECT dedup_key, COUNT(*) AS duplicate_count
FROM sales_items
GROUP BY dedup_key
HAVING COUNT(*) > 1;

SELECT 'purchase_orphan_rows' AS section, '' AS detail, '' AS value;
SELECT pi.id AS purchase_item_id, pi.receipt_id
FROM purchase_items pi
LEFT JOIN purchase_receipts pr ON pr.id = pi.receipt_id
WHERE pr.id IS NULL;

SELECT 'sales_orphan_rows' AS section, '' AS detail, '' AS value;
SELECT si.id AS sales_item_id, si.receipt_id
FROM sales_items si
LEFT JOIN sales_receipts sr ON sr.id = si.receipt_id
WHERE sr.id IS NULL;
