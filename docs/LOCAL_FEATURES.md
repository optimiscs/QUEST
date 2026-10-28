# QUEST 本地扩展与运行目录

基线为 `optimiscs/QUEST` 的 `main` 提交 `536acd47c83d5c1f6f5003b606aa0b8a2400a13f`；该基线本身已有本地摘要与记忆提示选项。本文件区分已经整合的功能与尚未验证的环节。原始训练与评估结果、模型和密钥均存放在本机 `workspace/`，不属于 Git 内容。

| 相对基线 | 入口 | 作用及边界 |
|---|---|---|
| 答案与工具修复 | `inference/react_agent.py` | Python 工具提示只插入一次；从 think 外的 answer 提取预测。此行为改变答案提取，旧结果不被改写。 |
| FAISS 索引修复 | `inference/search_faiss_bridge.py` | 不再重复添加首分片的 lookup。索引有效性仍须单独核对向量、lookup、唯一 ID 和语料。 |
| Jina / Serper 密钥轮换 | `inference/key_rotation/` | 可配置路径、跨进程锁及状态；只在无效凭据或明确额度耗尽时切换。密钥、状态和日志不纳入仓库。 |
| GAIA 作者评分与格式提示 | `evaluation/official_dataset/gaia.py`, `run_gaia_prompt.py` | 导入固定作者评分器；可选生成格式提示须显式开启。分数、旧提示设置和污染审计保持分开。 |
| 其他作者评分入口 | `evaluation/official_dataset/run.py` | 使用固定版本源码执行 DeepResearch Bench；对 BrowseComp/HLE 已知不兼容保持失败语义。不是所有数据集都已集成或验证。 |
| 作者评分兼容补丁 | `evaluation/official_dataset/compat/` | 保存 BrowseComp、HLE、WideSearch、Mind2Web-2、LiveResearchBench 的五份适配补丁及固定版本生成入口；仅创建独立副本，不修改作者源码或自动评分。截图切分和模型替换等差异需明确报告。 |
| DeepSeek 数据管线实验适配 | `contrib/deepseek_data/`, `task/` | 通过开关兼容 API、工具调用及开放题评分/导出；共用 DSML 解析并保留工具调用以外的文本。客观验证器执行、反馈重试、引用回填和端到端 SFT 数据导出仍未完成验证，不应当作生产就绪。 |
| 摘要 JSON 格式重试 | `inference/summary_utils.py`, `tool_visit.py` | 缓存和非缓存读页都检查每次格式重试结果；未能解析的不写入成功缓存；`VISIT_MAX_CONTENT_TOKENS` 限制长网页文本，默认保持 95000。使用 cl100k 计数，与模型实际 tokenizer 可能不同。 |
| 本地模型路由与 few-shot | `inference/local_model_gateway.py`, `inference/prompts/visit_fewshot_3.json` | 分离主模型和摘要/记忆请求，辅助模型多实例按当前网关在途请求数分配；仅摘要插入样例，支持仅关闭辅助 thinking。需显式启动并配置模型服务；不支持流式响应。网关计数不等于 vLLM 内部队列长度。 |
| 阶段观察 | `inference/observe.py` | 可选记录模型、搜索、网页读取、摘要、记忆和工具调用的开始/结束事件及耗时。完整请求/响应可能包含敏感内容，保存到私有目录；观察覆盖以实际函数映射为准，不等于所有外部调用都已自动记录。 |
| 轨迹工作区 | `web/` | 中英文页面、数据集切换、轨迹和时间线；`web/build_gaia.py` 可从现有跨度构建新视图，页面每 5 秒检查当前数据；已终止任务通过工作区元数据单独标记，原始轨迹和评分不变。历史数据及运行日志不提交。 |
| 64K QLoRA 配置样例 | `training_scripts/sft/examples/qlora64k_10pct.yaml` | 按已运行的四卡 10% 配置整理；路径是占位符，需要明确替换。使用独立 LlamaFactory v0.9.5，官方子模块版本不同。配置文件本身不会启动训练。 |

## 目录与安全边界

- `inference/`, `evaluation/`, `task/`, `training_scripts/` 维持原仓库功能分区；`web/` 为轨迹查看器。
- `workspace/` 是本机运行数据根，包含模型、缓存、环境、训练检查点、实验和轨迹；不进入 Git。其下并没有第二个 QUEST 开发仓库。
- 本次移除了旧兼容链接。历史日志中的旧路径保留原样作为证据；旧进程已经终止，不能按旧 PID 或历史路径直接恢复。当前维护用脚本和环境启动路径已经迁至 `workspace/`。
- `workspace/migrations/restructure-20261028-r1/` 保存进程终止记录、路径修改前备份和链接变更证据；目录可能含敏感配置，保持私有。
- 目录重构、配置和离线测试不代表论文完整复现；不自动启动训练或评估。

## 本地运行入口

```bash
# 轨迹网页（前台运行；不会启动评估）
workspace/env/bin/python web/serve.py --host 127.0.0.1 --port 6080

# 可选路由器；将地址与模型名换成自己已启动的服务
workspace/env/bin/python inference/local_model_gateway.py \
  --policy-upstream http://127.0.0.1:18000/v1 --policy-model POLICY_MODEL \
  --aux-upstream http://127.0.0.1:18100/v1 --aux-model AUX_MODEL \
  --fewshot inference/prompts/visit_fewshot_3.json --disable-aux-thinking

# 可选观察；运行参数由使用者自行指定
workspace/env/bin/python inference/observe.py --events workspace/private-events/run.jsonl \
  inference/run_multi_react.py --help
```

路由器的可选依赖列在 `inference/requirements-local-gateway.txt`。路由器接受 `QWEN38-POLICY`、`QWEN38-SUMMARY` 和 `QWEN38-MEMORY` 三个默认别名，可用 CLI 参数修改。多实例配置可以重复传入 `--aux-upstream`。模型服务的真实模型名称、上下文限制、并发和排队由实际部署配置决定。

### 路由与 QUEST 工具对接

以下变量只说明角色映射；设置变量或启动路由器都不会启动 QUEST 推理。

```bash
export HOSTNAME_LIST=127.0.0.1 PORTS=18300
export VISIT_LOCAL_PROMPT_ENABLED=true MEMORY_LOCAL_PROMPT_ENABLED=true
export VISIT_LOCAL_MODEL_NAME=QWEN38-SUMMARY
export MEMORY_LOCAL_MODEL_NAME=QWEN38-MEMORY
# 主模型应使用 --model QWEN38-POLICY；真实权重由上游服务决定。
```

若设置了 `SERVER_ENDPOINTS_FILE`，其中的 `HOSTNAME_LIST` / `PORTS` 优先于上述环境变量。`LOCAL_PROMPT_MODEL_NAME` 仍可作为两种工具的旧版共同回退值；单独设置角色名称可避免把记忆请求误认为摘要。按实验需要选择是否启用本地记忆提示，改变提示会影响评估可比性。
