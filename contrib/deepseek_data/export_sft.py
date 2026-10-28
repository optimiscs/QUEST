"""Export scored session snapshots; explicit ledger controls inclusion."""
import argparse, json, hashlib, os
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--ledger",required=True);p.add_argument("--output",required=True);p.add_argument("--manifest",required=True);a=p.parse_args()
ledger=Path(a.ledger).resolve(); rows=[]; decisions=[]; seen_rollouts=set()
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
for no,line in enumerate(ledger.read_text().splitlines(),1):
 if not line.strip(): continue
 rec=json.loads(line); reason=None
 kind=rec.get("kind"); score=rec.get("score"); threshold={"objective":1.0,"openended":0.475}.get(kind)
 task_id, rollout_id = rec.get("task_id"), rec.get("rollout_id")
 if task_id is not None and rollout_id is not None:
  identity=(str(kind),str(task_id),str(rollout_id))
  if identity in seen_rollouts: raise ValueError(f"duplicate task/rollout in ledger at line {no}")
  seen_rollouts.add(identity)
 if threshold is None or rec.get("score_status")!="scored" or not isinstance(score,(int,float)) or isinstance(score,bool) or not (0 <= score <= 1) or score < threshold: reason="not_scored_or_below_threshold"
 path=(ledger.parent/rec.get("sessions_path","")).resolve()
 if not reason and (not path.is_file() or not rec.get("task_id") or not rec.get("rollout_id")): reason="missing_sessions_or_provenance"
 count=0
 if not reason:
  for snapshot in path.read_text().splitlines():
   item=json.loads(snapshot); messages=item.get("messages")
   if not isinstance(messages,list) or not messages or any(not isinstance(x,dict) or not isinstance(x.get("role"),str) or not isinstance(x.get("content"),str) for x in messages): raise ValueError(f"invalid session in {path}")
   if not any(x.get("role")=="assistant" for x in messages): raise ValueError(f"session missing assistant in {path}")
   rows.append({"messages":messages});count+=1
  if not count: reason="empty_sessions"
 decisions.append({"ledger_line":no,"task_id":rec.get("task_id"),"rollout_id":rec.get("rollout_id"),"kind":kind,"score":score,"excluded_reason":reason,"sessions":count,"sessions_sha256":digest(path) if count else None})
out=Path(a.output);man=Path(a.manifest);out.parent.mkdir(parents=True,exist_ok=True);man.parent.mkdir(parents=True,exist_ok=True)
if out.exists() or man.exists(): raise FileExistsError("refusing to overwrite output or manifest")
out.write_text(json.dumps(rows,ensure_ascii=False,indent=2));man.write_text(json.dumps({"ledger_sha256":digest(ledger),"output_sha256":digest(out),"num_sessions":len(rows),"decisions":decisions},ensure_ascii=False,indent=2));print(json.dumps({"num_sessions":len(rows),"accepted_rollouts":sum(not d["excluded_reason"] for d in decisions),"total_rollouts":len(decisions)}))
