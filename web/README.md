# QUEST Web

FastAPI + PostgreSQL 的轨迹浏览器。前端使用 Vite、TypeScript 数据访问与搜索模块，以及原生 JavaScript 视图模块。保留原有 CSS、字体、图标和页面布局。

## 数据读取

打开工作区只查询运行信息和分页任务摘要；点击任务后一次获取该轨迹的全部事件正文。正文在展开时生成 DOM。搜索在 Worker 中执行，详情缓存按运行、轨迹和内容版本区分，按序列化字节数限制为 32 MiB。

浏览器每 5 秒检查轻量版本与统计，后台标签页暂停检查。其他任务发生变化时，当前轨迹事件 DOM 保持不变。HTTP 服务只查询数据库，不读取或解析来源 JSON。

## 本地安装和运行

需要 Python 3.11+、Node.js 24、PostgreSQL 14+。Web 使用独立 Python 环境，与推理/训练依赖分开。

```bash
make -C web setup
```

先创建数据库和专用用户，并设置连接地址（下面为本机开发示例）：

```bash
export VIEWER_DATABASE_URL='postgresql+psycopg://quest:quest@127.0.0.1:5432/quest_viewer'
make -C web migrate build import
make -C web serve
```

打开 `http://127.0.0.1:6080/trace-viewer-zh/`；原有 `?dataset=...#trace-245/overview` 链接继续有效。前台服务不自动运行评估任务。

另开终端运行数据导入进程：

```bash
make -C web watch
```

现有评估发布器继续输出规范化轨迹包，由独立导入进程发布到数据库。`build_gaia.py` 是这些发布器的数据转换工具，不参与 HTTP 请求。该适配器保留原始评分与停止标记，不启动模型或评分器。

开发时分别运行 `make -C web dev` 和 `make -C web frontend-dev`，Vite 将 `/api` 代理到 6081。后端配置从环境变量或当前工作目录的 `.env` 读取，配置名使用 `VIEWER_` 前缀。

## 目录

- `backend/`：API、数据模型、迁移、导入 CLI、数据库测试、OpenAPI 契约。
- `frontend/`：页面、视图模块、样式、类型生成、Worker、单元与浏览器测试。
- `tests/fixtures/`：前后端共享的合成测试数据。
- `scripts/`：契约生成、数据核对、测试数据导入工具。
- `deploy/`：容器构建和部署配置。
- `trace-viewer/data/`、`trace-viewer/datasets/`、`trace-viewer-zh/data/`：既有发布器的本机输入，均不提交 Git。
- `../workspace/viewer/`：本机环境、日志、验证结果等，不提交 Git。

## 检查

```bash
make -C web contracts check build
export VIEWER_TEST_DATABASE_URL='postgresql+psycopg://quest:quest@127.0.0.1:5432/quest_viewer_test'
VIEWER_DATABASE_URL="$VIEWER_TEST_DATABASE_URL" workspace/viewer/venv/bin/alembic -c web/backend/alembic.ini upgrade head
make -C web test
cd web/frontend
npx playwright install --with-deps chromium
npm run test:e2e
```

数据库测试要求专用数据库名以 `_test` 结尾。浏览器功能测试需要服务已运行且默认运行至少包含两条轨迹；CI 使用 `scripts/seed-test-data.py` 导入合成数据。视觉测试拦截 API 使用固定合成数据，比对迁移前捕获的桌面/手机截图，不依赖私人轨迹。

变更 API 后运行 `make -C web contracts`，同时提交 `backend/openapi.json` 和 `frontend/src/api/generated.ts`。CI 校验生成结果一致、代码检查、构建、数据库与浏览器测试。

详情核对：`workspace/viewer/venv/bin/python web/scripts/verify-import.py`。真实大型数据测试设置 `VIEWER_REAL_DATA=1` 后运行浏览器测试。性能采样工具是 `frontend/tests/performance/benchmark.mjs`。

部署、备份与回退见 [operations.md](docs/operations.md)，数据与事务设计见 [architecture.md](docs/architecture.md)。

当前轨迹底部状态栏展示轮次、已展示事件数、模型及工具调用耗时；点击可查看用量与上下文卡片。`sessionStats` 可选字段支持 `usage.inputTokens`、`usage.outputTokens`、`usage.totalTokens`、`usage.cachedInputTokens`、`usage.uncachedInputTokens`、`modelSeconds`、`toolSeconds`、`ttftSeconds`、`outputTokensPerSecond`，以及 `context.usedTokens`、`context.capacityTokens`、`context.systemTokens`、`context.toolTokens`、`context.messageTokens`。缺失字段显示“未记录”，不会按 0 估算。由 `build_gaia.py` 新生成的轨迹只在所有已完成策略模型调用均有用量记录时汇总其 token；不包括摘要、记忆或其他辅助模型。输出速度未单独记录时，按策略模型输出 token 总数除以模型调用总耗时计算，包含首 token 等待时间。已有轨迹需重新生成并导入后才会包含新汇总，原始记录缺失的数据仍不可用。
