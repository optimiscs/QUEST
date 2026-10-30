"""Read-only visible-answer judgment overlay shared by reports and the viewer."""
import hashlib
import json
from pathlib import Path


def visible_judging_finished(run):
    return not (run/'checks/visible-response-judge-policy.json').exists() or (run/'checks/visible-response-judge-complete.json').exists()


def apply_visible_judgment(run,case,row):
    if not (run/'checks/visible-response-judge-policy.json').exists() or row.get('agent_state')!='terminal':return row,None
    effective=dict(row,judge_state='pending',is_correct=None,judgment='等待仅最终可见回答的统一重评分；旧评分保留')
    receipt=run/'checks'/f'{case}-visible-response-judge.json'
    if not receipt.exists() or not row.get('result_path'):return effective,None
    try:
        data=json.loads(receipt.read_text());source=Path(row['result_path'])
        if (data.get('response_filter')!='visible_final_only'
                or Path(data.get('source_result_path','')).resolve()!=source.resolve()
                or data.get('source_result_sha256')!=hashlib.sha256(source.read_bytes()).hexdigest()):return effective,None
        if data.get('status')=='scored' and isinstance(data.get('is_correct'),bool):
            effective.update(judge_state='scored',is_correct=data['is_correct'],judgment='BrowseComp 官方判分提示；仅最终可见回答；本地 4B 裁判')
        else:effective.update(judge_state='unavailable',judgment='最终可见回答重评分未取得有效判词')
        return effective,data
    except (OSError,ValueError,TypeError):return effective,None
