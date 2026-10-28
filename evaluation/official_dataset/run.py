#!/usr/bin/env python3
"""Run the pinned dataset author DRBench evaluator in a fresh directory.

No evaluator code, prompts, responses, or scores are replaced here. The other
two upstream harnesses have known blockers and intentionally fail closed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = REPO_ROOT / 'workspace'
ROOT = Path(os.environ.get('QUEST_PROJECT_ROOT', str(WORKSPACE if (WORKSPACE / 'strict-reproduction').is_dir() else REPO_ROOT.parent)))
HOME_DIR = ROOT / 'strict-reproduction/official-dataset-eval-20261028'
SOURCES = HOME_DIR / 'sources'
PINS = {'browsecomp': ('simple-evals', '652c89d0ca9df547706735883097e9537d40dc47'),
        'hle': ('hle', '22ed3074b1e7b134bcbc09028d0ba320839b0655'),
        'drbench': ('deep-research-bench', 'f2735b5c3636759c22f9e936c0232de8bf545b67')}

def key_rotation_dir():
    """Locate the adapter from the source checkout, not the runtime workspace."""
    return REPO_ROOT / "inference/key_rotation"


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''): h.update(block)
    return h.hexdigest()

def rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def verify_source(benchmark):
    directory, expected = PINS[benchmark]
    root = SOURCES / directory
    actual = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    status = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    if actual != expected or status:
        raise RuntimeError(f'Upstream source mismatch or tracked files modified: {benchmark}')
    return root, actual

def run_stage(name, argv, env, work, out):
    start = time.time()
    log = out / 'logs' / (name + '.log')
    observer = Path(__file__).with_name('observe_official.py')
    wrapped = [argv[0], str(observer), str(out/'logs'/(name+'-api.jsonl')), *argv[1:]]
    with log.open('w') as f:
        process = subprocess.run(wrapped, cwd=work, env=env, stdout=f, stderr=subprocess.STDOUT)
    info = {'stage': name, 'argv': argv, 'exit_code': process.returncode,
            'wall_seconds': time.time() - start, 'log': str(log.relative_to(out))}
    with (out / 'stages.jsonl').open('a') as f: f.write(json.dumps(info) + '\n')
    print(json.dumps(info), flush=True)
    if process.returncode: raise RuntimeError(f'{name} failed; see {log}')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('benchmark', choices=PINS)
    parser.add_argument('--raw', type=Path, help='QUEST output converted to official DRBench id/prompt/article JSONL')
    parser.add_argument('--query', type=Path, help='Matching subset of the official query.jsonl')
    parser.add_argument('--out', type=Path, help='Fresh, nonexistent run directory under the independent output root')
    parser.add_argument('--workers', type=int, default=1)
    args = parser.parse_args()
    source, revision = verify_source(args.benchmark)
    if args.benchmark == 'hle':
        raise SystemExit('BLOCKED: official HLE uses Pydantic json_schema response_format; DeepSeek returned HTTP 400. No fallback was substituted.')
    if args.benchmark == 'browsecomp':
        raise SystemExit('BLOCKED: pinned official BrowseComp returns regex group(0) but compares it with yes/no. Scores can be wrong; source retained without modification.')
    if not all((args.raw, args.query, args.out)) or args.workers < 1:
        parser.error('drbench needs --raw, --query, --out, and positive --workers')
    allowed = (HOME_DIR / 'runs').resolve()
    out = args.out.resolve()
    if out == allowed or not out.is_relative_to(allowed): raise ValueError('Output must be a new child of the isolated runs directory')
    raw, query = args.raw.resolve(strict=True), args.query.resolve(strict=True)
    records, queries = rows(raw), rows(query)
    if not records or not queries: raise ValueError('Inputs must be nonempty')
    official_queries = {str(x['id']): x for x in rows(source / 'data/prompt_data/query.jsonl')}
    selected = {str(x['id']): x for x in queries}
    if len(selected) != len(queries) or len({str(x['id']) for x in records}) != len(records): raise ValueError('Duplicate IDs')
    for key, q in selected.items():
        if q != official_queries.get(key): raise ValueError(f'Query {key} differs from pinned official data')
    for item in records:
        q = selected.get(str(item.get('id')))
        if not q or item.get('prompt') != q.get('prompt') or not item.get('article'): raise ValueError('Raw records do not match official queries')
    if set(selected) != {str(x['id']) for x in records}: raise ValueError('Query/answer ID sets differ')
    config_path = Path(os.environ.get('QUEST_EVAL_API_CONFIG', str(ROOT / 'strict-reproduction/.secrets/api_config.json')))
    config = json.loads(config_path.read_text())['common']
    model = config['JUDGE_MODEL_NAME'].split('/')[-1]
    out.mkdir(parents=True, exist_ok=False)
    for name in ('logs', 'raw', 'cleaned', 'race', 'fact', 'work'): (out / name).mkdir()
    (out / 'work/data').symlink_to(source / 'data', target_is_directory=True)
    shutil.copyfile(raw, out / 'raw/quest.jsonl')
    shutil.copyfile(query, out / 'query.jsonl')
    manifest = {'benchmark': args.benchmark, 'source_commit': revision, 'model': model,
                'source_modified': False, 'raw_sha256': sha(raw), 'query_sha256': sha(query),
                'sample_ids': [str(x['id']) for x in records], 'status': 'running', 'stages': ['RACE', 'FACT']}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    key_rotation = key_rotation_dir()
    if not (key_rotation/'sitecustomize.py').is_file(): raise RuntimeError('Key rotation adapter is missing')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=os.pathsep.join((str(key_rotation), str(source))), QUEST_KEY_ROTATION='1',
               LLM_BACKEND='openai', OPENAI_API_KEY=config['API_KEY'], OPENAI_BASE_URL=config['API_BASE'],
               RACE_MODEL=model, CLEAN_MODEL=model, FACT_MODEL=model, JINA_API_KEY=config['JINA_API_KEYS'].split(',')[0])
    for name in ('HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'REQUESTS_CA_BUNDLE', 'SSL_CERT_FILE'):
        if config.get(name): env[name] = str(config[name])
    work = out / 'work'; py = sys.executable; queryfile = out / 'query.jsonl'; rawfile = out / 'raw/quest.jsonl'
    try:
        run_stage('race', [py, str(source / 'deepresearch_bench_race.py'), 'quest', '--raw_data_dir', str(out/'raw'), '--cleaned_data_dir', str(out/'cleaned'), '--query_file', str(queryfile), '--output_dir', str(out/'race'), '--max_workers', str(args.workers)], env, work, out)
        racefile = out/'race/raw_results.jsonl'
        if not racefile.is_file(): raise RuntimeError('RACE produced no results')
        scored = rows(racefile)
        if len(scored) != len(records) or {str(x.get('id')) for x in scored} != set(selected) or any('error' in x or not isinstance(x.get('overall_score'), (int, float)) for x in scored):
            raise RuntimeError('RACE did not produce one valid result for every input')
        fact = out / 'fact'; workers = str(args.workers)
        for name, module, argv in [
            ('extract', 'utils.extract', ['--raw_data_path', str(rawfile), '--output_path', str(fact/'extracted.jsonl'), '--query_data_path', str(queryfile), '--n_total_process', workers]),
            ('deduplicate', 'utils.deduplicate', ['--raw_data_path', str(fact/'extracted.jsonl'), '--output_path', str(fact/'deduplicated.jsonl'), '--query_data_path', str(queryfile), '--n_total_process', workers]),
            ('scrape', 'utils.scrape', ['--raw_data_path', str(fact/'deduplicated.jsonl'), '--output_path', str(fact/'scraped.jsonl'), '--n_total_process', workers]),
            ('validate', 'utils.validate', ['--raw_data_path', str(fact/'scraped.jsonl'), '--output_path', str(fact/'validated.jsonl'), '--query_data_path', str(queryfile), '--n_total_process', workers]),
            ('stat', 'utils.stat', ['--input_path', str(fact/'validated.jsonl'), '--output_path', str(fact/'fact_result.txt')])]:
            run_stage(name, [py, '-m', module, *argv], env, work, out)
        if not (fact/'fact_result.txt').is_file(): raise RuntimeError('FACT produced no result')
        manifest['status'] = 'completed_needs_result_audit'
    except BaseException as exc:
        manifest.update(status='failed', error=str(exc)); raise
    finally:
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

if __name__ == '__main__': main()
