import argparse,json,pathlib,hashlib,math
p=argparse.ArgumentParser();p.add_argument("--score",required=True);p.add_argument("--candidate",required=True);p.add_argument("--sessions",required=True);p.add_argument("--reference",required=True);p.add_argument("--reference-kind",choices=["independent_agent","provisional_generator"],required=True);p.add_argument("--out",required=True);a=p.parse_args()
paths={k:pathlib.Path(getattr(a,k)).resolve() for k in ["score","candidate","sessions","reference","out"]}
if paths["out"].exists():raise FileExistsError("refusing to overwrite ledger")
s=[json.loads(x) for x in paths["score"].read_text().splitlines() if x.strip()];c=[json.loads(x) for x in paths["candidate"].read_text().splitlines() if x.strip()];ss=[json.loads(x) for x in paths["sessions"].read_text().splitlines() if x.strip()]
if len(s)!=1 or len(c)!=1 or not ss or not any(v.get("is_final") for v in ss):raise ValueError("expected one score, one candidate, and complete final session")
x=s[0];q=c[0].get("question","");sc=x.get("final_score");iter_id=c[0].get("iter",1)
refs=[json.loads(x) for x in paths["reference"].read_text().splitlines() if x.strip()]
if len(refs)!=1: raise ValueError("expected one reference")
ref=refs[0]; text=ref.get("prediction",ref.get("answer","")); termination=str(ref.get("termination","")).lower()
if not isinstance(text,str) or len(text.strip())<100 or "answer not found" in text.lower() or "answer not found" in termination or "timeout" in termination: raise ValueError("reference incomplete; no score may be accepted")
status_path=paths["score"].with_suffix(".status.json")
status=json.loads(status_path.read_text())
for role in ("candidate","reference"):
 if status.get("input_sha256",{}).get(role)!=hashlib.sha256(paths[role].read_bytes()).hexdigest(): raise ValueError(role+" hash mismatch against score manifest")
if not q or not q.startswith(x.get("query", "")) or not x.get("query") or not isinstance(sc,(int,float)) or not math.isfinite(sc) or not 0<=sc<=1:raise ValueError("score, query, or provenance mismatch")
row={"task_id":str(x.get("id")),"rollout_id":str(iter_id),"kind":"openended","score_status":"scored" if a.reference_kind=="independent_agent" else "provisional_reference","score":sc,"sessions_path":str(paths["sessions"]),"score_path":str(paths["score"]),"candidate_path":str(paths["candidate"]),"reference_kind":a.reference_kind,"score_sha256":hashlib.sha256(paths["score"].read_bytes()).hexdigest()}
paths["out"].write_text(json.dumps(row,ensure_ascii=False)+"\n");print(json.dumps({"score":sc,"status":row["score_status"],"threshold":0.475}))
