import os,sys,json,subprocess,argparse,pathlib,hashlib
p=argparse.ArgumentParser();p.add_argument("--criteria",required=True);p.add_argument("--candidate",required=True);p.add_argument("--reference",required=True);p.add_argument("--out",required=True);args=p.parse_args();here=pathlib.Path(__file__).resolve().parent;root=here.parents[1]
paths={k:pathlib.Path(getattr(args,k)).resolve() for k in ["criteria","candidate","reference","out"]}
for k in ["criteria","candidate","reference"]:
 if not paths[k].is_file() or not paths[k].stat().st_size: raise ValueError(k+" missing or empty")
if paths["out"].exists(): raise FileExistsError("scoring output already exists")
for role in ("candidate", "reference"):
 for row in [json.loads(x) for x in paths[role].read_text().splitlines() if x.strip()]:
  termination = str(row.get("termination", "")).lower()
  content = row.get("prediction", row.get("answer", ""))
  if not isinstance(content, str) or len(content.strip()) < 100 or "answer not found" in content.lower() or "answer not found" in termination or "timeout" in termination:
   raise ValueError(role + " has incomplete or failed answer; refusing to score")
criteria=[json.loads(x) for x in paths["criteria"].read_text().splitlines() if x.strip()]
for c in criteria:
 w=c.get("dimension_weight",{});cs=c.get("criterions",{})
 if not isinstance(w,dict) or not isinstance(cs,dict) or not w or set(w)!=set(cs) or abs(sum(float(v) for v in w.values())-1)>0.02 or any(not isinstance(x,list) or not x for x in cs.values()):raise ValueError("criteria incomplete or weights invalid")
env=os.environ.copy();env["PYTHONUNBUFFERED"]="1";env["QUEST_DEEPSEEK_COMPAT"]="1";env.setdefault("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
if not env.get("DEEPSEEK_API_KEY"): raise RuntimeError("DEEPSEEK_API_KEY must be set")
script=root/"task/open_ended_eval/evaluate_criteria_args_parallel_open_ended.py"
cmd=[sys.executable,str(script),"--model","deepseek-flash","--prompt_to_eval",str(paths["criteria"]),"--answer_to_eval",str(paths["candidate"]),"--ref_to_eval",str(paths["reference"]),"--output_file",str(paths["out"]),"--hostname_list","localhost","--ports","8000","--max_workers","1"]
log=paths["out"].with_suffix(".log");status=paths["out"].with_suffix(".status.json");
with log.open("x") as f: proc=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=900)
rows=[json.loads(x) for x in paths["out"].read_text().splitlines() if x.strip()] if paths["out"].exists() else []
valid=[r for r in rows if isinstance(r.get("final_score"),(int,float)) and 0<=r["final_score"]<=1]
meta={"exit_code":proc.returncode,"result_rows":len(rows),"valid_scores":len(valid),"complete":proc.returncode==0 and len(valid)>0,"input_sha256":{k:hashlib.sha256(paths[k].read_bytes()).hexdigest() for k in ("criteria","candidate","reference")}}
status.write_text(json.dumps(meta,indent=2));print(json.dumps(meta));sys.exit(0 if meta["complete"] else 1)
