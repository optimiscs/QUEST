# Trace Viewer 数据 Schema

导入器读取的是一个**规范化后的单次评估运行包**（`traces.json`），不是原始
agent 日志。一个 JSON 文件对应一次评估运行；多个模型或多次 rollout 可以
注册成多个数据集。

## 文件位置

推荐把新评估放在：

```text
/root/autodl-tmp/Quest/web/trace-viewer/datasets/<eval-id>/traces.json
```

并在：

```text
/root/autodl-tmp/Quest/web/trace-viewer/datasets/index.json
```

注册。导入器将每个运行和单条轨迹写入数据库；前端源码统一位于 `web/frontend/`，不再直接读取这些文件。

当前内置文件夹：

- 英文原始轨迹：`trace-viewer/data/traces.json`
- 中文镜像：`trace-viewer-zh/data/traces.json`
- 额外评估：`trace-viewer/datasets/<eval-id>/traces.json`

## 顶层结构

```json
{
  "generatedAt": "2026-10-27T18:00:00+08:00",
  "run": {
    "name": "QUEST · My Benchmark",
    "model": "QUEST-4B",
    "benchmark": "My Benchmark",
    "date": "27 October 2026",
    "dateShort": "27 OCT 2026",
    "totalCases": 10,
    "judgePassed": 9,
    "judgeScored": 10,
    "rounds": 282,
    "inProgress": false,
    "toolCalls": 272,
    "pagesRead": 113,
    "searchQueries": 251,
    "searchCalls": 136,
    "wiki": "可选的硬件/运行说明"
  },
  "cases": []
}
```

`run` 字段会用于工作区摘要、面包屑、页脚和「数据与完整性说明」。

## Case 结构

每个 case 是一个任务/样本的完整轨迹：

```json
{
  "id": "trace-01",
  "index": 1,
  "field": "Ecology",
  "fieldZh": "生态学",
  "topic": "Invasive species",
  "topicZh": "入侵物种",
  "question": "用户问题原文",
  "answer": "34689",
  "answerNote": "答案的简短说明",
  "judge": "GAIA official normalized exact match",
  "correct": true,
  "inProgress": false,
  "groundTruth": "34689",
  "groundTruthTaskId": "17b5a6a3-bc87-42e8-b0fb-6ab0781ef2cc",
  "groundTruthLevel": "2",
  "rounds": 15,
  "durationSeconds": 374.2,
  "durationText": "6m 14s",
  "model": "QUEST-4B",
  "risk": { "level": "clean", "label": "No exposure detected" },
  "riskKey": "none_detected",
  "stats": {},
  "timing": {},
  "domains": [],
  "steps": [],
  "finalAnswer": "完整回答 Markdown",
  "keyIndices": [0, 1],
  "sources": ["https://example.com"]
}
```

### 必填字段（前端实际使用）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 唯一 id，如 `trace-01` |
| `index` | number | 1 开始的序号 |
| `field` / `fieldZh` | string | 领域；中文页面用 `fieldZh` |
| `topic` / `topicZh` | string | 主题；中文页面用 `topicZh` |
| `question` | string | 任务问题 |
| `answer` | string | 最终答案（保持原始字面量） |
| `answerNote` | string | 答案补充说明 |
| `correct` | boolean / null | 评审是否通过；未评分时为 `null` |
| `inProgress` | boolean | 可选；是否仍在运行 |
| `groundTruth` | string | 可选；官方标准答案 |
| `groundTruthTaskId` | string | 可选；官方标注 task id |
| `groundTruthLevel` | string | 可选；官方标注难度 |
| `rounds` | number | 轮次数 |
| `durationSeconds` | number | 总耗时（秒） |
| `durationText` | string | 显示用耗时 |
| `model` | string | 模型名称 |
| `risk.level` | `clean` / `warn` / `alert` | 来源暴露审计 |
| `stats` | object | 见下 |
| `timing` | object | 见下 |
| `domains` | array | 来源域名计数 |
| `steps` | array | 轨迹步骤 |
| `finalAnswer` | string | 完整回答，支持 Markdown |
| `keyIndices` | number[] | 可选，预留给关键步骤索引 |
| `sources` | string[] | 可选，来源 URL 列表 |

`judge`、`riskKey`、`resultLabel` 可留作原始审计信息；当前界面主要使用
`correct`、`inProgress` 和 `risk.level`。

### 任务状态

任务索引（现已更名为「评估轨迹」）的右侧状态点按以下规则显示：

| 条件 | 颜色 | 标签 |
|---|---|---|
| `inProgress === true` | 蓝色 | 进行中 |
| `inProgress !== true` 且 `correct === true` | 绿色 | 通过 |
| 其他（`correct === false` 或 `null`） | 红色 | 评估错误 |

如果 case 有 `groundTruth`，对话概览和轨迹结论会显示「标准答案」按钮；
点击后对比官方答案与模型答案。缺省时按钮隐藏。

### `stats`

```json
{
  "steps": 15,
  "searchCalls": 8,
  "readCalls": 6,
  "computeCalls": 0,
  "searchQueries": 17,
  "resultsScanned": 114,
  "pagesRead": 6,
  "uniqueSources": 5,
  "uniqueDomains": 2,
  "maxPromptTokens": 19004,
  "maxOutputTokens": 1406,
  "averageStepSeconds": 24.7,
  "longestStepSeconds": 59.5
}
```

`maxPromptTokens`、`maxOutputTokens` 当前仅作元数据；其余值用于摘要与筛选。

### `timing`

```json
{
  "model": 224.6,
  "search": 35.5,
  "read": 65.1,
  "compute": 0,
  "overhead": 3.6,
  "total": 374.2
}
```

单位均为秒。`read` 包含读取与摘要；`overhead` 可为 0。

### `domains`

```json
[
  { "domain": "nas.er.usgs.gov", "count": 5 },
  { "domain": "pinellas.gov", "count": 1 }
]
```

## Step 结构

每个 step 代表一次模型输出 + 它发起的工具调用（最终答案为一次纯模型
输出）。

```json
{
  "n": 1,
  "kind": "search",
  "label": "搜索",
  "thought": "模型推理文本",
  "model_seconds": 19.55,
  "tool_seconds": 9.06,
  "modelStart": 0.01,
  "modelEnd": 19.56,
  "toolStart": 19.56,
  "toolEnd": 28.62,
  "tool": {}
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `n` | number | 第几轮 |
| `kind` | `search` / `read` / `compute` / `answer` | 步骤类型 |
| `label` | string | 显示名，如「搜索」「读取」「综合」 |
| `thought` | string | 推理/思考原文 |
| `model_seconds` | number | 模型输出耗时 |
| `tool_seconds` | number | 工具耗时 |
| `modelStart` / `modelEnd` | number | 相对运行起点的秒数，用于时间线 |
| `toolStart` / `toolEnd` | number/null | 工具调用时间；answer 步为 null |
| `tool` | object/null | 工具详情；answer 步为 null |

`modelStart`/`toolStart` 是时间线真实位置所必需的。如果原始日志没有绝对
时间，可以按 `modelEnd = modelStart + model_seconds` 推导，并让工具调用紧接
在模型之后。

## 工具对象

### `search`

```json
{
  "name": "search",
  "kind": "search",
  "goal": "",
  "queries": [
    {
      "query": "USGS Amphiprion ocellaris",
      "seconds": 1.8,
      "count": 10,
      "results": [
        {
          "title": "clown anemonefish",
          "url": "https://example.org/page",
          "domain": "example.org",
          "snippet": "搜索摘要"
        }
      ]
    }
  ],
  "queryCount": 1,
  "issuedQueryCount": 1,
  "resultCount": 10
}
```

### `read`

```json
{
  "name": "visit",
  "kind": "read",
  "goal": "提取页面信息",
  "pages": [
    {
      "url": "https://example.org/page",
      "domain": "example.org",
      "title": "Page title",
      "summary": "页面摘要",
      "rationale": "为什么这页相关",
      "evidence": "提取到的原文/证据",
      "readerSeconds": 12.4,
      "summarySeconds": 8.2
    }
  ],
  "pageCount": 1
}
```

### `compute`

```json
{
  "name": "PythonInterpreter",
  "kind": "compute",
  "goal": "",
  "code": "print('hello')",
  "stdout": "stdout:\nhello\n",
  "language": "python"
}
```

### `answer`

```json
"tool": null
```

## 最小可用评估

为了确保图表、日志、概览都能工作，建议**完整**提供上述字段；只提供部分
字段会导致 UI 缺少摘要或时间线。若只有原始日志，可先写一个 adapter 把它
映射成上面的结构，再放入 `datasets/<eval-id>/traces.json`。活跃 GAIA 运行
的 `scripts/build_viewer.py` 已自动从
`judge/ground-truth/gaia-103-org.json` 注入标准答案字段。

## 对齐与计数

- `run.totalCases` 应等于 `cases.length`。
- `run.rounds` 应等于各 case `rounds` 之和。
- `run.toolCalls` / `run.searchCalls` / `run.readCalls` 用于全局摘要和底部 dock。
- 每个 case 的 `stats.steps` 应等于 `steps.length`。
- 时间线的 `total` 建议取 `run/case` 的实际总时长；超出总时长的 span 会自动控制到 100% 以内。
