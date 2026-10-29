"""Summarize binary judgments without treating missing judgments as wrong."""

def summarize(results, filenames):
    by_question = {}
    by_file = {}
    def merge(old, new):
        if old is True or new is True: return True
        if old is None or new is None: return None
        return False
    for row in results:
        q, filename = row.get('question', ''), row['file']
        value = row.get('is_correct')
        value = value if isinstance(value, bool) else None
        qmap = by_question.setdefault(q, {})
        qmap[filename] = merge(qmap[filename], value) if filename in qmap else value
        fmap = by_file.setdefault(filename, {})
        fmap[q] = merge(fmap[q], value) if q in fmap else value
    def counts(values):
        total=len(values); correct=sum(v is True for v in values); unscored=sum(v is None for v in values)
        return {'correct':correct, 'total':total, 'unscored':unscored, 'accuracy':correct/total if total and not unscored else None}
    best={}
    for k in range(1,len(filenames)+1):
        values=[]
        for qmap in by_question.values():
            trials=[qmap.get(f) for f in filenames[:k]]
            values.append(True if True in trials else None if None in trials else False)
        best[f'best@{k}']=counts(values)
    return {'total_questions':len(by_question), 'best_at_k':best, 'by_file':{f:counts(list(m.values())) for f,m in by_file.items()}}
