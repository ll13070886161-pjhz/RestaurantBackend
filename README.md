# 图片解析生成 Excel 报表

上传商品图片，调用火山 Doubao 多模态模型识别商品信息，自动输出 Excel 报表。

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. 环境变量

先复制示例文件再填写：

```bash
cp .env.example .env
```

在 `.env` 中配置（以 `app/core/config.py` 为唯一读取来源）：

```env
APP_HOST=0.0.0.0
APP_PORT=8000
UPLOAD_DIR=temp_uploads
OUTPUT_DIR=outputs

LLM_PROVIDER_NAME=volcengine
LLM_API_KEY=你的火山 API Key
LLM_MODEL_NAME=doubao-1.5-thinking-vision-pro
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_TIMEOUT=45
DB_URL=sqlite:///./app.db
LOG_LEVEL=INFO
```

如果使用 MySQL，把 `DB_URL` 改成：

```env
DB_URL=mysql+pymysql://root:your_password@127.0.0.1:3306/image2excel?charset=utf8mb4
```

也可以改成分字段配置（推荐）：

```env
DB_TYPE=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=image2excel_app
DB_PASS=your_password
DB_NAME=image2excel
DB_PARAMS=charset=utf8mb4
```

并先在 MySQL 中创建库：

```sql
CREATE DATABASE image2excel CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

创建专用账号（推荐，不用 root）：

```sql
CREATE USER 'image2excel_app'@'%' IDENTIFIED BY 'your_strong_password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX ON image2excel.* TO 'image2excel_app'@'%';
FLUSH PRIVILEGES;
```

检查数据库连通性：

```bash
make db-check
```

## 3. 启动服务

```bash
make dev
```

首次初始化可执行：

```bash
make init
```

## 3.1 从 SQLite 迁移到 MySQL（可选）

1. 确认 `.env` 中的 `DB_URL` 已配置为 MySQL。
2. 保留当前 SQLite 文件 `app.db`（默认来源）。
3. 执行迁移：

```bash
make migrate-mysql
```

说明：
- 迁移脚本会先清空 MySQL 目标表，再从 SQLite 全量导入。
- 如需改 SQLite 来源，可临时指定：

```bash
SRC_DB_URL=sqlite:///./app.db make migrate-mysql
```

## 4. 使用流程

1. 浏览器访问 `http://localhost:8000`
2. 上传一张或多张商品图片
3. 等待识别完成并预览结果
4. 点击“下载最新Excel”

## 访问与权限

- 查看类接口（如库存、采购明细、营业明细）可远程访问。
- 识别接口可所有客户端访问。
- 数据库写入接口（保存入库）受 `WRITE_ALLOWED_IPS` 控制，默认仅本机。
- 如需允许你的局域网主机写入，可在 `.env` 设置，例如：

```env
WRITE_ALLOWED_IPS=127.0.0.1,::1,localhost,192.168.1.10
INVENTORY_ALERT_POPUP_ENABLED=true
INVENTORY_ALERT_OPENCLAW_ENABLED=false
INVENTORY_ALERT_OPENCLAW_WEBHOOK_URL=
INVENTORY_ALERT_FEISHU_WEBHOOK_URL=
```

库存预警说明：
- 在“库存查看”里可对每条物料设置“启用预警 + 阈值”。
- 进入页面时会调用 `/api/inventory/alerts`，若低于阈值会弹窗提醒。
- 点击“发送飞书预警”会触发 `/api/inventory/alerts?trigger_notify=true`，可按配置通过 OpenClaw webhook 与飞书 webhook 推送。

## 字段模板

- `product_name`
- `unit_price`
- `quantity`
- `amount`
- `order_created_at`（默认上传时间）
- `remarks`

## 厂商适配说明

默认实现在 `app/services/provider_other.py`，当前已按火山 Doubao-1.5-thinking-vision-pro 的 OpenAI 兼容接口方式配置。若后续切换厂商，只需调整这个文件的 `parse_image` 方法。
