# 搜索行为图谱 / Search Behavior Atlas

用于比较不同评估轨迹中的搜索行为：是围绕同一个问题反复改写，还是不断引入新方向、新实体和新约束。

## 页面

- 路径：`/search-behavior.html`
- 数据：`frontend/public/assets/search-behavior.json`（构建后为 `/assets/search-behavior.json`）
- 前端：`frontend/search-behavior.html`、`frontend/src/search-behavior.{css,js}`
- 数据生成：`web/scripts/build_search_behavior.py`

## 指标

- 完全重复：归一化 query 字符串相同。
- 近重复：与历史 query 的 token Jaccard ≥ 0.75。
- 逐步拓展：Jaccard 0.30–0.75，保留部分核心词并引入新词。
- 新方向：Jaccard < 0.30。
- 首条 query 不计入重复率；重复率 =（完全重复 + 近重复）/ 后续 query 数。
- 拓展率 =（逐步拓展 + 新方向）/ 后续 query 数。

轨迹标签：

- 反复追问：重复率 ≥ 45%，且新方向 < 35%。
- 持续拓展：重复率 < 30%，且拓展率 ≥ 70%。
- 混合迭代：其余情况。
- 单次检索：只有一次搜索。

## 更新数据

```bash
cd /root/autodl-tmp/Quest
python web/scripts/build_search_behavior.py
cp web/search-behavior/data.json web/frontend/public/assets/search-behavior.json
cd web/frontend
export PATH=/root/autodl-tmp/codex-cli-runtime/node-v24.22.1-linux-x64/bin:$PATH
./node_modules/.bin/vite build
```

新增 HTML 页面后需要重启 FastAPI viewer，让启动时的页面路由扫描注册到新页面。

## 说明

页面使用数据快照，不实时轮询。数据只保留 query、轮次、结果数、耗时和分类，不包含完整 thought、网页正文或答案内容。
