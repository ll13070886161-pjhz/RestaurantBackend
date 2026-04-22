# SQLite 快速查看与健康检查

数据库文件：`/Users/ai/Downloads/data/image2excel/app.db`

## 1) 进入数据库

```bash
sqlite3 "/Users/ai/Downloads/data/image2excel/app.db"
```

## 2) 基础查看命令（交互式）

```sql
.tables
.schema
.schema purchase_items
.headers on
.mode column
SELECT * FROM purchase_receipts LIMIT 20;
SELECT * FROM purchase_items LIMIT 20;
```

## 3) 每表行数

```sql
SELECT 'daily_summaries' AS table_name, COUNT(*) AS row_count FROM daily_summaries
UNION ALL SELECT 'product_records', COUNT(*) FROM product_records
UNION ALL SELECT 'purchase_items', COUNT(*) FROM purchase_items
UNION ALL SELECT 'purchase_receipts', COUNT(*) FROM purchase_receipts
UNION ALL SELECT 'sales_items', COUNT(*) FROM sales_items
UNION ALL SELECT 'sales_receipts', COUNT(*) FROM sales_receipts;
```

## 4) 索引与去重核查

```sql
PRAGMA index_list('purchase_items');
PRAGMA index_info('ix_purchase_items_dedup_key');
PRAGMA index_list('sales_items');
PRAGMA index_info('ix_sales_items_dedup_key');
```

## 5) 导出 CSV

非交互式导出：

```bash
sqlite3 "/Users/ai/Downloads/data/image2excel/app.db" -header -csv "SELECT * FROM purchase_items;" > purchase_items.csv
```

交互式导出：

```sql
.headers on
.mode csv
.once purchase_items.csv
SELECT * FROM purchase_items;
```

## 6) 业务核对 SQL（建议每次导入后执行）

可直接运行 `scripts/sql/health_check.sql`：

```bash
sqlite3 "/Users/ai/Downloads/data/image2excel/app.db" < scripts/sql/health_check.sql
```
