"""Validate benchmark artifacts before exposing a score to QUEST's viewer.

A successful exit code alone is not proof that an evaluator completed its work.
The numerical values are retained exactly as emitted by each benchmark.
"""
import json
import math
from pathlib import Path


def _load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def classify(benchmark, out):
    out = Path(out)
    if benchmark == 'liveresearchbench':
        dimensions = {}
        for criterion in ('presentation', 'coverage', 'consistency', 'citation', 'depth'):
            files = list((out / 'results').rglob(f'{criterion}_results.jsonl'))
            if len(files) != 1:
                continue
            try:
                rows = [json.loads(line) for line in files[0].read_text().splitlines() if line.strip()]
                result = rows[-1].get(f'{criterion}_grading_results', {}) if rows else {}
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(result, dict) or result.get('error'):
                continue
            if criterion in ('presentation', 'coverage'):
                summary = result.get('summary', {})
                value = summary.get('average_pass_rate', summary.get('percentage_addressed'))
                if not result.get('evaluations'):
                    continue
            elif criterion == 'depth':
                value = {k: result.get(k) for k in ('winner_comparison_1', 'winner_comparison_2')}
                if not all(v in ('evaluated_model', 'reference_model', 'tie', 'A', 'B') for v in value.values()):
                    continue
            else:
                value = result.get('score')
            if criterion != 'depth' and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                continue
            dimensions[criterion] = value
        missing = sorted(set(('presentation', 'coverage', 'consistency', 'citation', 'depth')) - dimensions.keys())
        # Preserve the official dimensions and their different scales; do not
        # fabricate a combined score or pass/fail threshold.
        return {'status': 'needs_audit' if missing else 'scored_dimensions', 'dimensions': dimensions,
                'limitations': [f'missing_{name}' for name in missing],
                'reason': 'incomplete_dimensions' if missing else None}
    if benchmark == 'browsecomp_plus':
        files = list((out / 'results').rglob('run_*_eval.json'))
        data = _load(files[0]) if len(files) == 1 else None
        evidence = None
        inputs = list((out / 'input').glob('run_*.json'))
        run = _load(inputs[0]) if len(inputs) == 1 else None
        if isinstance(run, dict) and isinstance(run.get('retrieval_trace'), dict):
            from browsecomp_plus.quest_adapter import evidence_metrics
            from browsecomp_plus.scripts_evaluation.evaluate_with_openai import load_qrel_data, extract_citations_from_response, compute_citation_metrics
            qrel_file = Path(__file__).parent / 'browsecomp_plus/topics-qrels/qrel_evidence.txt'
            if qrel_file.is_file():
                evidence = evidence_metrics(run, load_qrel_data(qrel_file), extract_citations_from_response, compute_citation_metrics)
        if isinstance(data, dict) and data.get('is_completed') is False:
            return {'status': 'no_answer', 'reason': 'no_final_answer', 'evidence': evidence}
        if not isinstance(data, dict) or data.get('is_completed') is not True:
            return {'status': 'needs_audit', 'reason': 'missing_completion_status', 'evidence': evidence}
        judge = data.get('judge_result', {}) if isinstance(data, dict) else {}
        if judge.get('parse_error') is False and isinstance(judge.get('correct'), bool):
            result = {'status': 'scored', 'is_correct': judge['correct'], 'judgment': str(judge.get('extracted_final_answer', '')), 'evidence': evidence}
            if evidence is not None:
                result['judge_prompt_version'] = 'browsecomp_plus_official'
            if evidence is None:
                result['limitations'] = ['retrieval_and_citation_metrics_not_available']
            elif evidence['status'] != 'complete':
                result['limitations'] = [evidence['status']]
            return result
        return {'status': 'needs_audit', 'reason': 'missing_or_invalid_judge_result', 'evidence': evidence}
    if benchmark == 'widesearch':
        data = _load(out / 'result.json')
        if isinstance(data, dict) and isinstance(data.get('score'), (float, int)) and not isinstance(data['score'], bool) and math.isfinite(data['score']):
            msg = str(data.get('msg') or '')
            if msg.startswith('evaluator error:'):
                return {'status': 'failed', 'reason': msg}
            result = {'status': 'scored', 'score': data['score'], 'judgment': msg}
            if msg == 'response_df is None':
                result['limitations'] = ['official_zero_unparseable_response']
            return result
        return {'status': 'needs_audit', 'reason': 'missing_or_invalid_score'}
    if benchmark == 'mind2web2':
        files = list((out / 'results').glob('*/*/answer_1/results/*.json'))
        logs = list((out / 'results').glob('**/answer_1/logs/*.log'))
        failures = ('TargetClosedError', 'BrowserType.launch:', 'Missing X server', 'Traceback (most recent call last)', 'error_type=')
        if any(any(marker in p.read_text(errors='replace') for marker in failures) for p in logs):
            return {'status': 'failed', 'reason': 'verification_tool_error'}
        data = _load(files[0]) if len(files) == 1 else None
        if isinstance(data, dict) and isinstance(data.get('final_score'), (int, float)) and not isinstance(data['final_score'], bool) and math.isfinite(data['final_score']) and data.get('eval_breakdown'):
            return {'status': 'scored', 'score': data['final_score'], 'judgment': 'Mind2Web2 final_score'}
        return {'status': 'needs_audit', 'reason': 'missing_or_invalid_score'}
    if benchmark == 'drbench':
        files = list((out / 'results/race').glob('*/raw_results.jsonl'))
        if len(files) != 1:
            return {'status': 'failed', 'reason': 'missing_race_results'}
        try:
            rows = [json.loads(x) for x in files[0].read_text().splitlines() if x.strip()]
        except (OSError, ValueError):
            rows = []
        if len(rows) != 1 or not isinstance(rows[0], dict) or 'error' in rows[0]:
            return {'status': 'failed', 'reason': 'invalid_race_results'}
        score = rows[0].get('overall_score')
        if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score):
            return {'status': 'needs_audit', 'reason': 'missing_race_score'}
        result = {'status': 'scored', 'score': score, 'judgment': 'DRBench RACE overall_score'}
        facts = list((out / 'results/fact').glob('*/fact_result.txt'))
        scraped = list((out / 'results/fact').glob('*/scraped.jsonl'))
        if scraped and 'scrape failed:' in scraped[0].read_text(errors='replace'):
            result['limitations'] = ['fact_citation_retrieval_failed']
        elif not facts:
            result['limitations'] = ['fact_not_evaluated']
        elif 'valid_rate: null' in facts[0].read_text():
            result['limitations'] = ['fact_not_evaluable_no_validated_citations']
        return result
    return {'status': 'needs_audit', 'reason': 'benchmark_requires_audit'}
