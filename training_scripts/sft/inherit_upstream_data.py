"""Reuse upstream task acceptance; select only unchanged, harness-valid data.

No LLM judge or generation is invoked. Missing local rubric artifacts do not
invalidate the user's explicit decision to trust the released SFT dataset.
"""
import argparse
import collections
import json
from pathlib import Path
import sys
import time
import zlib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'training_scripts/sft'))
sys.path.insert(0,str(ROOT))
from optimize_summary_data import Pipeline, write, jsonl, sha
from inference import native_tools, source_ids
from replay_cleaning_pilot import search_format
from select_summary1024 import FINAL_PROMPT


def verify_conversion(original, converted):
    """Compare all task messages after the explicitly allowed representation edits."""
    messages=converted['messages']
    if messages[-2]!={'role':'user','content':FINAL_PROMPT}:
        raise ValueError('unexpected_final_instruction')
    actual=native_tools.prepare_messages(messages[: -2]+messages[-1:])
    if len(actual)!=len(original):raise ValueError('message_count_changed')
    registry=source_ids.SourceRegistry(Path(converted['metadata']['source_map']).parent)
    mapping=registry._read()
    if len(set(mapping.values()))!=len(mapping):raise ValueError('non_bijective_source_map')
    expected=[];pending=None
    for i,old in enumerate(original):
        item=dict(old)
        if i==0:
            # System instructions are intentionally replaced with the current
            # harness. All user, assistant and tool content remains checked.
            expected.append(actual[0]);continue
        if item['role']=='tool' and pending=='search':item['content']=search_format(item['content'])
        # Tool evidence can contain literal course/bill IDs such as S241.
        # Require known URLs here, but apply source-ID validation to policy
        # messages only, as the chronological runtime converter does.
        expected.append(registry.compact(item,allow_new=False,
                                        check_source_ids=item['role']=='assistant'))
        if item['role']=='assistant':
            calls=item.get('tool_calls',[]);pending=calls[0]['function']['name'] if calls else None
    expected=native_tools.prepare_messages(expected)
    if expected!=actual:raise ValueError('substantive_message_change')
    registry.validate_final(json.loads(messages[-1]['content'])['answer'])
    return {'status':'pass','checked_messages':len(actual)-1,
            'allowed_changes':['current system prompt','native tool representation','search result headings',
                               'bijective URL-to-source-ID substitution','explicit finalization instruction'],
            'checked_content_sha256':sha(actual[1:])}


def select_rows(rows, original_ids, flexible=False):
    ordered=sorted(rows,key=lambda r:(r['metadata']['id'] not in original_ids,
                                     sha(('upstream-select',r['metadata']['id']))))
    selected=[];seen=set();counts=collections.Counter();remaining=[]
    for row in ordered:
        m=row['metadata'];key=(m['kind'],m['stratum']);quota=192 if m['kind']=='objective' else 64
        if m['question_sha256'] in seen:continue
        if counts[key]<quota:
            selected.append(row);seen.add(m['question_sha256']);counts[key]+=1
        else:remaining.append(row)
    if flexible:
        # Preserve the initial per-kind/length quotas where possible, then fill
        # unavailable slots from another stratum. Never repeat a question.
        for row in remaining:
            if len(selected)==1024:break
            m=row['metadata']
            if m['question_sha256'] in seen:continue
            selected.append(row);seen.add(m['question_sha256']);counts[(m['kind'],m['stratum'])]+=1
    return selected,counts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--flexible-mix',action='store_true')
    args=parser.parse_args();args.inherit_upstream=True
    pipeline=Pipeline(args);out=pipeline.out
    quality_policy={'task_acceptance':'inherited_upstream','authorization':'User confirmed original SFT release was accepted upstream.',
                    'locally_rejudged':False,'original_rubric_unchanged':True,
                    'old_question_only_judgments_used':False,'fresh_generation_enabled':False,
                    'flexible_mix':args.flexible_mix,'training_started':False}
    policy_file=out/'upstream-acceptance-policy.json'
    if policy_file.exists() and json.loads(policy_file.read_text())!=quality_policy:
        raise RuntimeError('Selection policy changed; use a new output version')
    write(policy_file,quality_policy)
    samples=list(map(json.loads,(pipeline.source/'sample16-aligned-v2.jsonl').read_text().splitlines()))
    by_case={r['metadata']['case']:r['metadata']['question_sha256'] for r in samples}
    findings=json.loads((pipeline.source/'first12-analysis.json').read_text())['confirmed_findings']
    known_defects={by_case[f['case']]:f['finding'] for f in findings if f['kind']=='static'}
    rows=[];counts=collections.Counter();start=time.time();processed=0
    def progress(final=False):
        selected,strata=select_rows(rows,set(pipeline.original_meta),args.flexible_mix)
        jsonl(out/'accepted-partial.jsonl',selected)
        status={'stage':'upstream_selection_complete' if final else 'upstream_harness_screening',
                'processed':processed,'eligible_sessions':len(rows),'selected':len(selected),'target':1024,
                'selected_by_kind':dict(collections.Counter(r['metadata']['kind'] for r in selected)),
                'selected_by_stratum':{str(k):v for k,v in strata.items()},'checks':dict(counts),
                'task_acceptance':'inherited_upstream','local_llm_reviews':0,'training_started':False,
                'seconds':round(time.time()-start,1),'updated_epoch':time.time()}
        write(out/'status.json',status);print(json.dumps(status),flush=True)
        return selected
    # All open rows are inspected; objective rows are inspected until every
    # length stratum has enough distinct questions plus a replacement margin.
    order=list(pipeline.original_meta.values())+[m for m in pipeline.plan if m['id'] not in pipeline.original_meta]
    unique_by_stratum=collections.defaultdict(set)
    for meta in order:
        key=(meta['kind'],meta['stratum'])
        if meta['kind']=='objective' and len(unique_by_stratum[key])>=320:continue
        processed+=1;ident=meta['id'];receipt_path=out/'inheritance-checks'/(ident+'.json')
        if meta['question_sha256'] in known_defects:
            counts['known_defect_quarantine']+=1
            write(receipt_path,{'status':'quarantine','reason':known_defects[meta['question_sha256']],
                                'scope':'same-question variants held for targeted review; not a claim all variants are wrong',
                                'origin':'concrete_static_findings; not question-only rubric verdict'})
            continue
        row=pipeline.convert(meta)
        if row is None:
            counts['harness_rule_reject']+=1;continue
        try:
            original=json.loads(zlib.decompress(pipeline.db.execute('SELECT messages FROM pool WHERE id=?',(ident,)).fetchone()[0]))
            check=verify_conversion(original,row)
        except (ValueError,KeyError,TypeError) as exc:
            counts['conversion_quarantine']+=1;write(receipt_path,{'status':'quarantine','reason':str(exc)})
            continue
        rubric=pipeline.original_rubrics.lookup(row['metadata'])
        row['metadata'].update(quality_status='upstream_accepted_harness_checked',
            task_acceptance={'basis':'user_confirmed_upstream_release','local_rejudgment':False,
                             'source_file':row['metadata']['file'],'source_row':row['metadata']['row'],
                             'source_session_id':ident},
            original_rubric={'local_artifact_status':rubric['status'],'origin':rubric['origin'],
                             'tree_sha256':rubric.get('tree_sha256'),
                             'note':'Artifact availability does not replace inherited upstream acceptance.'},
            conversion_receipt=str(receipt_path))
        write(receipt_path,check);write(out/'records'/(ident+'.json'),row)
        rows.append(row);unique_by_stratum[key].add(meta['question_sha256']);counts['pass']+=1
        if processed%64==0:progress()
    selected=progress(final=True)
    jsonl(out/'eligible-upstream-sessions.jsonl',rows)
    if len(selected)!=1024:
        write(out/'job-result.json',{'status':'insufficient_harness_compatible_data_for_requested_mix',
            'selected':len(selected),'target':1024,'upstream_acceptance_reused':True,'training_started':False})
        return
    jsonl(out/'candidates1024.jsonl',selected)
    sample=[]
    for kind,n in (('objective',3),('openended',1)):
        for bucket in range(4):
            group=[r for r in selected if r['metadata']['kind']==kind and r['metadata']['stratum']==bucket]
            sample.extend(sorted(group,key=lambda r:sha(('upstream-regression',r['metadata']['id'])))[:n])
    if len(sample)!=16:raise ValueError('Insufficient strata for 16-case regression')
    for i,row in enumerate(sample):row['metadata']=dict(row['metadata'],case=f'case{i:02d}')
    jsonl(out/'sample16-static.jsonl',sample)
    write(out/'job-result.json',{'status':'selected_pending_token_export_and_regression','sessions':1024,
                                'upstream_acceptance_reused':True,'training_started':False})


if __name__=='__main__':main()
