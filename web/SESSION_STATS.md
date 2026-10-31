# 轨迹会话统计

`GET /api/v1/runs/{run_id}/traces/{trace_id}/session-stats` 返回最近一次导入的 `sessionStats` 和 `timing`，ETag 为轨迹版本。页面每 5 秒轮询；数据源仍由各运行的发布器和数据库导入器更新（BrowseComp 发布器目前约每 60 秒一次），因此不是逐 token 推送。仅统计已完成的主模型调用；进行中的请求、辅助模型和失败重试不计入 token 用量。

新 Agent 默认通过 OpenAI 兼容流式接口记录 TTFT：从发起 HTTP 请求到首个有效内容、推理或工具调用增量。它包括客户端和排队时间；不等于纯 GPU prefill。`QUEST_TELEMETRY_STREAM=0` 可关闭，TTFT 随之不可用。总 TPS 仍为累计输出 token 除以已记录主模型调用耗时，不是解码 TPS。

模型服务启动脚本默认传 `--enable-prompt-tokens-details`。缓存量使用服务端 `prompt_tokens_details.cached_tokens`，缓存未命中量为输入总量减缓存量。若历史调用没有明细，只汇总有明细的调用并显示覆盖数量；重启服务前的缓存量无法还原。上下文已用量为最近一次完成请求的 `prompt_tokens`，容量来自 `/v1/models` 的 `max_model_len`，可通过 `QUEST_CONTEXT_CAPACITY_TOKENS` 显式指定。上下文分类使用模型本地 tokenizer 分别计算消息文本及工具 JSON，是近似值，可能不包含模板或格式开销，不作为计费依据。`QUEST_TELEMETRY_TOKEN_BREAKDOWN=0` 关闭 tokenizer 的主动加载。

修改采集代码不会改变已运行的 Agent；它们仍使用启动时加载的代码。新启动的 Agent 才能记录 TTFT 和分类信息。已有 Agent 在服务重启后仍可接收服务器返回的缓存用量；过去未记录的值仍显示未记录。仅重启 Web 后端不会中断评估或模型服务。
