"""Write a candid release gate and per-session review manifest."""
import collections
import hashlib
import json
from pathlib import Path
import sys


def main():
    run = Path(sys.argv[1]).resolve()
    read = lambda name: json.loads((run / name).read_text())
    quality = read('quality-assessment.json')
    runtime = read('runtime-audit.json')
    rollout = read('rollout-status.json')
    parity = read('parity-report.json')
    tokens = read('tokenization-report.json')
    rows = list(map(json.loads, (run / 'sft1024-summary-native-v2.jsonl').read_text().splitlines()))
    samples = list(map(json.loads, (run / 'sample16-aligned-v2.jsonl').read_text().splitlines()))
    case_by_id = {r['metadata']['id']: r['metadata']['case'] for r in samples}
    reviews = {r['case']: r for r in quality['cases'] if r['kind'] == 'static'}
    manifest = []
    for row in rows:
        meta = row['metadata']; case = case_by_id.get(meta['id']); review = reviews.get(case)
        status = 'not_sampled'
        if review:
            status = ('sample_context_review_pass' if review['context_review_pass'] else
                      'needs_review' if review['status'] != 'assessed' else 'sample_quality_concern')
        manifest.append({'id': meta['id'], 'kind': meta['kind'], 'case': case,
                         'quality_status': status, 'review': review})
    (run / 'quality-manifest1024.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in manifest))
    gate = 'not_passed' if any(r['quality_status'] in ('needs_review', 'sample_quality_concern') for r in manifest) else 'unverified'
    report = {
        'selected_sessions': len(rows), 'kind_counts': dict(collections.Counter(r['metadata']['kind'] for r in rows)),
        'training_turns': tokens['supervised_turns'], 'max_training_tokens': tokens['max_tokens'],
        'truncated': tokens['truncated'], 'loss_tokens': tokens['loss_tokens'],
        'rollout_completed': rollout['completed'], 'rollout_exit_codes': [r['exit_code'] for r in rollout['results']],
        'prompt_token_parity': {'checked': parity['checked_prompts'], 'all_equal': parity['all_equal']},
        'runtime': runtime, 'quality': quality['summary'],
        'session_quality_counts': dict(collections.Counter(r['quality_status'] for r in manifest)),
        'quality_gate': gate, 'training_started': False, 'retrieval_mode': 'summary',
        'limitations': quality['limitations'] + [
            'Memory sessions preserve supplied post-condenser context; missing earlier trajectories were not reconstructed.',
            'Automatic memory may skip because it rechecks the older-history subset against the full-context threshold; see per-case warnings.',
            'First four raw event logs contain terminating preflight workers. Derived views retain attributable primary policy/tool threads and omit auxiliary timing.',
            'Viewer legacy error count includes completed unscored cases and is not an inference-failure count.',
        ],
        'artifacts_sha256': {name: hashlib.sha256((run / name).read_bytes()).hexdigest() for name in
                            ('sft1024-summary-native-v2.jsonl', 'sample16-aligned-v2.jsonl', 'tokenized-turns.parquet')},
    }
    (run / 'validation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for name in ('training-data-contract.json', 'selection-report.json'):
        contract = read(name); contract['quality_status'] = 'sample_quality_gate_' + gate
        (run / name).write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n')
    q = quality['summary']; completed = rollout['completed']
    note = f"""# 摘要模式 SFT 候选与 16 条回归验证

选出 1024 个不同任务：768 条客观、256 条开放。按可见工具调用次数四分位分层，保留 517 条带历史记忆的会话，没有按短轮次优先排序。带记忆会话是压缩后的片段，不代表恢复了原任务全部历史。

数据文件：`sft1024-summary-native-v2.jsonl`。训练载入：`tokenized-dataset/`，6115 个逐 assistant 回合样本，只对目标 assistant tokens 计 loss；每个目标监督一次，最大 19692 tokens，没有截断。通用 OpenAI 数据转换器可能丢掉工具调用的 reasoning，请直接使用已编码数据。

16 条固定样本包含 12 条客观、4 条开放；已完成推理 {completed}/16。94 个静态 assistant 提示与实际服务的 token IDs 完全相同。实际请求协议和最终短 ID 引用检查见 `runtime-audit.json`。

质量门禁：**尚未通过，未启动训练**。静态摘要上下文审核通过 {q['static']['context_review_pass']}/{q['static']['reviewed']}；新推理回答通过 {q['fresh']['context_review_pass']}/{q['fresh']['reviewed']}。这两项不是官方准确率。审核使用同一模型和提供的搜索片段、页面摘要，历史记忆未独立验证，16 条也是训练任务中的回归样本，不能证明全部 1024 条合格。逐条疑点见 `quality-assessment.json`，未抽样的 1008 条仍未完成语义质检。

保留原始判词与引用格式复核结果，不把 valid source ID 缺少原始 URL 误判为错误。`quality-manifest1024.jsonl` 标注抽样通过、存在疑点、待人工核查及未抽样状态。下一轮应处理疑点、对储备池使用相同质量门禁补齐 1024 条，再评估 BM25+embedding；本轮未替换页面摘要。

长轨迹还暴露了记忆压缩的二次阈值检查：主循环按完整上下文触发，而 condenser 对移除最近三轮后的子集再次检查，可能跳过并被上层记为解析警告。逐条真实更新和警告数已记录，不能把触发次数视为成功压缩次数。

Web：选择 `SFT 1024 · 摘要回归 16 · 27B`。这批不是官方 benchmark，页面旧版 error 计数包含未评分完成项，请结合运行退出码和质量报告判断。前四条重启时旧 worker 写入了同一路径；原日志保留，发布和审计使用明确归属新进程的主任务线程事件，保留政策/工具输入输出，省略无法归属的辅助计时。所有过滤有 provenance 记录。
"""
    (run / 'README.md').write_text(note)
    print(json.dumps({'completed': completed, 'quality_gate': gate, 'quality': q}, ensure_ascii=False))


if __name__ == '__main__':
    main()
