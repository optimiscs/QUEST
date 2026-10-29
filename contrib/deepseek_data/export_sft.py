"""Export scored session snapshots; explicit ledger controls inclusion."""
import argparse, json, hashlib, os
from pathlib import Path
try:
    from .evidence import validate
except ImportError:
    from evidence import validate


def main():
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
     # No trusted objective-verifier execution/provenance contract exists yet.
     # A caller-supplied score or a structural summary is not acceptance evidence.
     if not reason and kind == "objective": reason="objective_verifier_unverified"
     path=(ledger.parent/rec.get("sessions_path","")).resolve()
     if not reason and (not path.is_file() or not rec.get("task_id") or not rec.get("rollout_id")): reason="missing_sessions_or_provenance"
     if not reason and kind == "openended":
      for role in ("sessions", "score", "candidate", "reference", "status"):
       location=rec.get(role+"_path"); expected=rec.get(role+"_sha256")
       if not isinstance(location,str) or not isinstance(expected,str):
        raise ValueError(f"missing {role} provenance at ledger line {no}")
       evidence=(ledger.parent/location).resolve()
       if not evidence.is_file() or digest(evidence)!=expected:
        raise ValueError(f"changed or missing {role} evidence at ledger line {no}")
     if not reason and kind == "openended":
      evidence_result=validate(*((ledger.parent/rec[role+"_path"]).resolve() for role in ("score", "candidate", "reference", "sessions", "status")), rec.get("reference_kind"))
      if any(rec.get(key) != evidence_result[key] for key in ("task_id", "rollout_id", "score", "score_status")):
       raise ValueError(f"ledger disagrees with evidence at line {no}")
     count=0
     if not reason:
      for item in evidence_result["sessions"]:
       messages=item.get("messages")
       if not isinstance(messages,list) or not messages or any(not isinstance(x,dict) or not isinstance(x.get("role"),str) or not isinstance(x.get("content"),str) for x in messages): raise ValueError(f"invalid session in {path}")
       if not any(x.get("role")=="assistant" for x in messages): raise ValueError(f"session missing assistant in {path}")
       rows.append({"messages":messages});count+=1
      if not count: reason="empty_sessions"
     decisions.append({"ledger_line":no,"task_id":rec.get("task_id"),"rollout_id":rec.get("rollout_id"),"kind":kind,"score":score,"excluded_reason":reason,"sessions":count,"sessions_sha256":digest(path) if count else None})
    out=Path(a.output);man=Path(a.manifest);out.parent.mkdir(parents=True,exist_ok=True);man.parent.mkdir(parents=True,exist_ok=True)
    if out.exists() or man.exists(): raise FileExistsError("refusing to overwrite output or manifest")
    if out.resolve() == man.resolve(): raise ValueError("output and manifest must be distinct")
    try:
     with out.open("x", encoding="utf-8") as stream:
      stream.write(json.dumps(rows,ensure_ascii=False,indent=2))
     try:
      with man.open("x", encoding="utf-8") as stream:
       json.dump({"ledger_sha256":digest(ledger),"output_sha256":digest(out),"num_sessions":len(rows),"decisions":decisions},stream,ensure_ascii=False,indent=2)
     except BaseException:
      out.unlink(missing_ok=True)
      raise
    except FileExistsError:
     raise FileExistsError("refusing to overwrite output or manifest")
    print(json.dumps({"num_sessions":len(rows),"accepted_rollouts":sum(not d["excluded_reason"] for d in decisions),"total_rollouts":len(decisions)}))


if __name__ == "__main__":
    main()
