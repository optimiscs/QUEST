"""Run paired GAIA retrieval trials, publishing native viewer datasets."""
import contextlib
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from inference.gaia_scheduler import select_gpu
PROJECT = REPO / 'workspace'
RUN = PROJECT / 'strict-reproduction/gaia-retrieval-ab-20261029-r1'
SOURCE = PROJECT / 'strict-reproduction/gaia-sft32-27b-2plus2-20261028-r2'
SITE = REPO / 'web/trace-viewer'
PYTHON = PROJECT / 'env/bin/python'
PORTS = [18210, 18201, 18202]
DIRECT = {'baseline': ('', 'summary'), 'bm25-direct': ('bm25', 'direct'),
          'embedding-direct': ('embedding', 'direct'), 'bm25-reranker-direct': ('bm25_reranker', 'direct'),
          'hybrid-direct': ('hybrid', 'direct'), 'hybrid-reranker-direct': ('hybrid_reranker', 'direct')}
METHODS = {'bm25-direct': 'bm25', 'embedding-direct': 'embedding', 'bm25-reranker-direct': 'bm25_reranker',
           'hybrid-direct': 'hybrid', 'hybrid-reranker-direct': 'hybrid_reranker'}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def health(port):
    import requests
    try:
        return requests.get(f'http://127.0.0.1:{port}/health', timeout=2).ok
    except requests.RequestException:
        return False


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    lock = (RUN / 'controller.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state_path = RUN / 'controller-state.json'
    resume = '--resume-direct-complete' in sys.argv[1:]
    resume_active = '--resume-active' in sys.argv[1:]
    if state_path.exists() and not (resume or resume_active):
        raise RuntimeError('existing experiment state requires explicit resume; refusing to overwrite')
    if (resume or resume_active) and not state_path.exists():
        raise RuntimeError('cannot resume without an existing state')
    scorer_path = PROJECT / 'strict-reproduction/official-sources/gaia-leaderboard/scorer.py'
    revision = subprocess.check_output(['git', '-C', str(scorer_path.parent), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != '9f133d71362e77b3539f1514f31b9c101a545fec':
        raise RuntimeError('GAIA official scorer revision mismatch')
    spec = importlib.util.spec_from_file_location('official_gaia_scorer', scorer_path)
    scorer = importlib.util.module_from_spec(spec); spec.loader.exec_module(scorer)
    refs = json.loads((SOURCE / 'judge/ground-truth/gaia-103-org.json').read_text())
    by_question = {x['Question']: x for x in refs}
    cases = [f'row{i:04d}' for i in range(32)]
    if resume or resume_active:
        state = json.loads(state_path.read_text())['groups']
        if set(state) != set(DIRECT) or any(set(rows) != set(cases) or (resume and any(row.get('agent_state') != 'terminal' for row in rows.values())) for rows in state.values()):
            raise RuntimeError('resume requires every direct group to be terminal and no summary group to have started')
    else:
        state = {group: {case: {'agent_state': 'pending', 'judge_state': 'pending'} for case in cases} for group in DIRECT}
    running = {}
    groups = dict(DIRECT)
    retrieval_servers = {}

    def start_retrieval_server(role, gpu, port, batch):
        if health(port) or role in retrieval_servers:
            return
        model = PROJECT / 'models' / ('Qwen3-Embedding-8B' if role == 'embedding' else 'Qwen3-Reranker-8B')
        index_path = model / 'model.safetensors.index.json'
        if not index_path.exists():
            return
        weights = set(json.loads(index_path.read_text())['weight_map'].values())
        if not all((model / name).is_file() for name in weights):
            return
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(gpu), TOKENIZERS_PARALLELISM='false')
        log = RUN / 'logs' / f'{role}-server.log'; log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a') as output:
            retrieval_servers[role] = subprocess.Popen([str(PYTHON), '-u', str(REPO/'inference/retrieval_model_server.py'), '--role', role, '--model', str(model), '--port', str(port), '--batch-size', str(batch)], env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)

    def prepare(group):
        root = RUN / group
        for directory in ('configs', 'logs', 'checks', 'judge/ground-truth', 'results', 'traces', 'cache'):
            (root / directory).mkdir(parents=True, exist_ok=True)
        (root / 'judge/ground-truth/gaia-103-org.json').write_bytes((SOURCE / 'judge/ground-truth/gaia-103-org.json').read_bytes())
        for idx, case in enumerate(cases):
            (root / 'configs' / f'{case}.jsonl').write_bytes((SOURCE / 'configs' / f'{case}.jsonl').read_bytes())
            (root / 'configs' / f'{case}-server_endpoints.conf').write_text(f'HOSTNAME_LIST=127.0.0.1\nPORTS={PORTS[idx % 3]}\n')

    def publish():
        comparison = {}
        index_path = SITE / 'datasets/index.json'
        index = json.loads(index_path.read_text())
        for group, rows in state.items():
            root = RUN / group
            snap = {'epoch': time.time(), 'total': 32, 'cases': rows}
            write_json(root / 'status.json', snap)
            comparison[group] = {'correct': sum(v.get('is_correct') is True for v in rows.values()),
                                 'scored': sum(v.get('judge_state') == 'scored' for v in rows.values()),
                                 'terminal': sum(v.get('agent_state') == 'terminal' for v in rows.values()), 'total': 32}
            ident = 'gaia-retrieval-ab-20261029-' + group
            dest = SITE / 'datasets' / ident
            subprocess.run([str(PYTHON), str(REPO / 'web/build_gaia.py'), '--run-root', str(root), '--output-dir', str(dest), '--label', 'GAIA32 ' + group, '--include-running', '--replace-existing'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            if (dest / 'traces.json').exists() and not any(x.get('id') == ident for x in index['datasets']):
                index['datasets'].append({'id': ident, 'label': 'GAIA32 · ' + group, 'description': '筛选与摘要对照实验', 'folder': 'datasets/' + ident, 'data': 'datasets/' + ident + '/traces.json', 'benchmark': 'GAIA32', 'visible': True})
        write_json(index_path, index)
        write_json(SITE / 'datasets/gaia-retrieval-ab-comparison.json', {'updated': time.time(), 'groups': comparison})
        write_json(RUN / 'controller-state.json', {'groups': state, 'comparison': comparison})

    if not resume_active:
        for group in groups:
            prepare(group)
    else:
        class AdoptedProcess:
            def __init__(self, pid, group, case):
                self.pid, self.group, self.case = pid, group, case
            def poll(self):
                try:
                    proc_state = Path(f'/proc/{self.pid}/stat').read_text().split(') ', 1)[1][0]
                    if proc_state != 'Z': return None
                except (OSError, IndexError):
                    pass
                files = list((RUN/self.group/'results'/self.case).rglob('iter1.jsonl'))
                return 0 if len(files) == 1 else 1
        adopted = json.loads((RUN/'adopt-active.json').read_text())
        for item in adopted:
            group,case,pid,gpu = item['group'],item['case'],item['pid'],item['gpu']
            if group not in state or case not in state[group] or not 0 <= gpu < 3:
                raise RuntimeError('invalid adopted process inventory')
            state[group][case].update(agent_state='running',agent_pid=pid)
            running[group,case] = (AdoptedProcess(pid,group,case),gpu)
        for group,rows in state.items():
            for case,row in rows.items():
                if (group,case) in running or row.get('agent_state') == 'terminal': continue
                files = list((RUN/group/'results'/case).rglob('iter1.jsonl'))
                if files or row.get('agent_state') == 'running':
                    running[group,case] = (AdoptedProcess(row.get('agent_pid',-1),group,case),int(case[3:])%3)
                    row['agent_state'] = 'running'
    stage = 'direct'
    publish()
    last_publish = time.monotonic()
    while True:
        start_retrieval_server('embedding', 3, 18213, 8)
        start_retrieval_server('reranker', 4, 18214, 4)
        for (group, case), (proc, gpu) in list(running.items()):
            rc = proc.poll()
            if rc is None:
                continue
            del running[group, case]
            row = state[group][case]; row.update(agent_state='terminal', agent_returncode=rc, judge_state='unavailable')
            files = list((RUN / group / 'results' / case).rglob('iter1.jsonl'))
            if rc == 0 and len(files) == 1:
                result = json.loads(files[0].read_text().splitlines()[-1]); row['result_path'] = str(files[0])
                reference = by_question.get(result.get('question')); answer = result.get('prediction')
                if reference and isinstance(answer, str) and answer.strip() and answer.strip().lower() not in ('answer not found.', 'no answer found.'):
                    with (RUN / group / 'logs' / f'{case}-scorer.log').open('w') as output, contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                        row.update(judge_state='scored', is_correct=bool(scorer.question_scorer(answer, reference['answer'])), judgment='GAIA official normalized exact match')
        slots = [sum(gpu == i for _, gpu in running.values()) for i in range(3)]
        for case in cases:
            for group, (method, delivery) in groups.items():
                if state[group][case]['agent_state'] != 'pending': continue
                if method in ('embedding', 'hybrid', 'hybrid_reranker') and not health(18213): continue
                if method in ('bm25_reranker', 'hybrid_reranker') and not health(18214): continue
                gpu = select_gpu(slots, lambda i: health(PORTS[i]))
                if gpu is None: break
                root = RUN / group
                (root/'configs'/f'{case}-server_endpoints.conf').write_text(f'HOSTNAME_LIST=127.0.0.1\nPORTS={PORTS[gpu]}\n')
                env = dict(os.environ, QUEST_AB_PROJECT=str(PROJECT), QUEST_AB_GROUP_ROOT=str(root), QUEST_AUDIT_CASE=case, QUEST_AUDIT_MODE='agent', VISIT_EXPERIMENT_METHOD=method, VISIT_EXPERIMENT_DELIVERY=delivery, VISIT_EMBEDDING_URL='http://127.0.0.1:18213', VISIT_RERANKER_URL='http://127.0.0.1:18214', VISIT_EXPERIMENT_AUDIT=str(root/'logs'/f'{case}-retrieval.jsonl'))
                with (root/'logs'/f'{case}-agent.stdout.log').open('w') as output:
                    proc = subprocess.Popen([str(PYTHON), '-u', str(REPO/'inference/scripts/observe_retrieval_ab.py')], cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                running[group, case] = (proc, gpu); slots[gpu] += 1
                state[group][case].update(agent_state='running', agent_pid=proc.pid, agent_started_epoch=time.time())
        if time.monotonic() - last_publish >= 30:
            publish(); last_publish = time.monotonic()
        if not running and all(v['agent_state'] == 'terminal' for rows in state.values() for v in rows.values()):
            if stage == 'direct':
                sys.path.insert(0, str(REPO))
                from evaluation.gaia_retrieval_decision import decide
                retry_path = RUN/'checks/retry-required.json'
                retries = json.loads(retry_path.read_text()).get('cases', []) if retry_path.exists() else []
                decision = decide(state, retries)
                if decision['decision'] == 'pending':
                    if resume_active and decision.get('reason') == 'retry_incomplete':
                        write_json(RUN/'decision.json', decision)
                        break
                    time.sleep(3)
                    continue
                if decision['decision'] == 'inconclusive':
                    write_json(RUN/'decision.json', decision)
                    break
                if decision['decision'] == 'skip_flash':
                    write_json(RUN/'decision.json', decision)
                    break
                for group in decision['selected']:
                    name = group.removesuffix('-direct') + '-summary'
                    groups[name] = (METHODS[group], 'summary')
                    state[name] = {case: {'agent_state': 'pending', 'judge_state': 'pending'} for case in cases}
                    prepare(name)
                write_json(RUN/'decision.json', decision)
                stage = 'summary'
            else:
                break
        time.sleep(3)
    publish()


if __name__ == '__main__':
    main()
