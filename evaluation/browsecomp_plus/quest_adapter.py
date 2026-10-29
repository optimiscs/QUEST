"""Map QUEST search traces to BrowseComp+ evidence metrics without inventing IDs."""
import json
import re
from pathlib import Path

_DOC = re.compile(r'(?m)^Link:\s*bm25://([0-9]+)\s*$')


def collect_retrieval(events_path, prediction):
    """Recover only returned search-result IDs; incomplete histories are labeled."""
    events_path = Path(events_path) if events_path else None
    if events_path and events_path.is_file():
        events = []
        malformed = False
        for line in events_path.read_text().splitlines():
            try: events.append(json.loads(line))
            except ValueError: malformed = True
        starts = [i for i, e in enumerate(events) if e.get('event') == 'process_start']
        if starts:
            events = events[starts[-1]:]
        search = {e.get('span_id'): e for e in events if e.get('kind') == 'tool' and e.get('event') == 'span_start' and str((e.get('input') or {}).get('tool_name','')).lower() == 'search'}
        ends = {e.get('span_id'): e for e in events if e.get('kind') == 'tool' and e.get('event') == 'span_end' and e.get('span_id') in search}
        ids = set()
        for item in ends.values():
            if isinstance(item.get('output'), str): ids.update(_DOC.findall(item['output']))
        complete = bool(starts) and not malformed and any(e.get('event') == 'process_done' for e in events) and len(search)==len(ends)
        return {'docids': sorted(ids, key=lambda x:(len(x),x)), 'complete': complete, 'source': 'agent_events', 'search_calls': len(search), 'finished_search_calls': len(ends)}
    # Memory compaction can remove earlier tool responses. Preserve this partial
    # evidence for inspection, never treat it as a complete retrieval history.
    ids=set();count=0
    for msg in prediction.get('messages', []):
        if msg.get('role') not in ('user','tool'): continue
        content=msg.get('content')
        if isinstance(content,str) and '<tool_response>' in content:
            matches=_DOC.findall(content)
            if matches:count+=1;ids.update(matches)
    return {'docids': sorted(ids,key=lambda x:(len(x),x)), 'complete': False, 'source': 'retained_messages_partial', 'search_calls': None, 'observed_search_responses': count}


def build_run(prediction, events_path):
    qid=str(prediction.get('filename') or '').strip()
    if not qid:raise ValueError('missing query ID')
    info=collect_retrieval(events_path, prediction)
    answer=(prediction.get('prediction') or '').strip()
    complete=answer.lower() not in ('','answer not found.','no answer found.')
    return {'query_id':qid, 'status':'completed' if complete else 'incomplete',
            'retrieved_docids':info['docids'], 'retrieval_trace':info,
            'tool_call_counts':{'search':info['search_calls']} if info['search_calls'] is not None else {},
            'result':[{'type':'output_text','output':prediction.get('prediction') or ''}]}


def evidence_metrics(run, qrels, extract_citations, compute_citation_metrics):
    qid=str(run['query_id']);relevant=qrels.get(qid,[])
    if not relevant:
        return {'status':'unavailable', 'reason':'missing_query_evidence', 'retrieval_recall':None, 'citation_metrics':None}
    answer=run['result'][-1].get('output','') if run.get('result') else ''
    cited=extract_citations(answer) if run.get('status')=='completed' else []
    citation=compute_citation_metrics(cited,relevant) if run.get('status')=='completed' else None
    retrieved=run.get('retrieved_docids',[])
    complete=run.get('retrieval_trace',{}).get('complete') is True
    return {'status':'complete' if complete else 'partial_retrieval', 'relevant_count':len(relevant),
            'retrieved_count':len(set(retrieved)), 'retrieval_recall':len(set(retrieved)&set(relevant))/len(relevant) if complete else None,
            'observed_recall_lower_bound':len(set(retrieved)&set(relevant))/len(relevant) if not complete else None,
            'cited_docids':cited, 'citation_metrics':citation, 'retrieval_trace':run.get('retrieval_trace',{})}
