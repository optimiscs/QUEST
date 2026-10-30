import hashlib
import json
from inference.visible_judge_state import apply_visible_judgment,visible_judging_finished


def test_visible_policy_hides_legacy_score_until_uniform_regrade(tmp_path):
 (tmp_path/'checks').mkdir();(tmp_path/'checks/visible-response-judge-policy.json').write_text('{}')
 old={'agent_state':'terminal','judge_state':'scored','is_correct':True,'result_path':str(tmp_path/'result.jsonl')}
 row,receipt=apply_visible_judgment(tmp_path,'row0000',old)
 assert row['judge_state']=='pending' and row['is_correct'] is None and receipt is None
 assert old['is_correct'] is True and not visible_judging_finished(tmp_path)


def test_visible_receipt_requires_same_source_content_and_preserves_original(tmp_path):
 (tmp_path/'checks').mkdir();(tmp_path/'checks/visible-response-judge-policy.json').write_text('{}')
 source=tmp_path/'result.jsonl';source.write_text('original evidence')
 old={'agent_state':'terminal','judge_state':'scored','is_correct':True,'result_path':str(source)}
 receipt={'source_result_path':str(source),'source_result_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'response_filter':'visible_final_only','status':'scored','is_correct':False}
 (tmp_path/'checks/row0000-visible-response-judge.json').write_text(json.dumps(receipt))
 row,data=apply_visible_judgment(tmp_path,'row0000',old)
 assert row['is_correct'] is False and data==receipt and old['is_correct'] is True
 source.write_text('different evidence')
 assert apply_visible_judgment(tmp_path,'row0000',old)[0]['judge_state']=='pending'


def test_unrelated_datasets_and_running_cases_keep_their_existing_state(tmp_path):
 row={'agent_state':'running','judge_state':'pending'}
 assert apply_visible_judgment(tmp_path,'row0000',row)==(row,None)
 assert visible_judging_finished(tmp_path)
