#!/usr/bin/env python3
"""Audit full-credit objective verifier summaries without running verifier code.

This is a structural check only. It does not establish rubric coverage, source
provenance, isolation, or model correctness, and cannot approve SFT data.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path


def audit_summary(summary):
    if not isinstance(summary,dict):raise ValueError('summary must be an object')
    value=summary.get('final_score')
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:
        raise ValueError('invalid final_score')
    breakdown=summary.get('eval_breakdown')
    if not isinstance(breakdown,list) or len(breakdown)!=1 or not isinstance(breakdown[0],dict):
        raise ValueError('expected exactly one evaluation breakdown')
    tree=breakdown[0].get('verification_tree')
    if not isinstance(tree,dict) or tree.get('id')!='root':raise ValueError('missing root verification tree')
    seen=set(); count=0; leaves=0; stack=[tree]
    while stack:
        node=stack.pop()
        if not isinstance(node,dict):raise ValueError('tree node must be an object')
        ident=node.get('id'); status=node.get('status'); score=node.get('score');children=node.get('children')
        if not isinstance(ident,str) or not ident or ident in seen:raise ValueError('missing or duplicate tree node id')
        seen.add(ident);count+=1
        if not isinstance(children,list):raise ValueError('tree node children must be a list')
        if not isinstance(node.get('critical'),bool) or node.get('strategy') not in ('parallel','sequential'):
            raise ValueError('invalid node strategy or criticality')
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:
            raise ValueError('invalid node score')
        if status not in ('passed','failed','partial','skipped','initialized'):
            raise ValueError('invalid node status')
        if (status=='passed' and score!=1) or (status in ('failed','skipped') and score!=0) or (status=='partial' and not 0<score<1):
            raise ValueError('node status/score mismatch')
        if not children:leaves+=1
        stack.extend(children)
    if count<2 or leaves<1:raise ValueError('verification tree has no checks')
    if not math.isclose(value,tree.get('score'),rel_tol=1e-9,abs_tol=1e-9):raise ValueError('final and root scores differ')
    if value==1 and any_node_not_passed(tree):
        raise ValueError('full-credit summary contains a non-passing node')
    return {'structural_status':'full_credit_consistent' if value==1 else 'not_full_credit',
            'reported_score':value,'tree_nodes':count,'leaf_nodes':leaves,
            'provenance_status':'unverified','training_eligible':False}


def any_node_not_passed(tree):
    pending=[tree]
    while pending:
        node=pending.pop()
        if node.get('status')!='passed' or node.get('score')!=1:return True
        pending.extend(node.get('children',[]))
    return False


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--summary',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True,help='New audit file, never overwritten')
    a=p.parse_args()
    raw=a.summary.read_bytes();summary=json.loads(raw)
    result=audit_summary(summary)
    result['summary_sha256']=hashlib.sha256(raw).hexdigest()
    result['note']='Structure only; no verifier execution, source or sandbox attestation, or SFT approval.'
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))

if __name__=='__main__':main()
