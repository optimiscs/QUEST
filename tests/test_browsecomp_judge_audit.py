import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('judge_audit',Path(__file__).resolve().parents[1]/'inference/scripts/audit_browsecomp_judge.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_matching_extracted_answer_with_negative_verdict_is_reviewed_only():
 receipt={'raw':'extracted_final_answer: Poland—a Country of Folklore?\ncorrect: no','is_correct':False}
 flags=module.review_flags(receipt,'Exact Answer: Poland — a Country of Folklore?','Poland — a Country of Folklore?')
 assert 'incorrect_but_extracted_answer_matches_reference' in flags
 assert 'incorrect_but_reference_text_present' in flags
 assert receipt['is_correct'] is False


def test_reference_mentioned_as_rejected_candidate_is_flagged_without_changing_score():
 receipt={'raw':'extracted_final_answer: Other Film\ncorrect: no','is_correct':False}
 flags=module.review_flags(receipt,'The Gods Must Be Crazy was considered, but my answer is Other Film.','The Gods Must Be Crazy')
 assert flags==['incorrect_but_reference_text_present']
 assert receipt['is_correct'] is False


def test_positive_semantic_variation_and_hallucinated_extraction_still_flagged():
 assert module.review_flags({'raw':'extracted_final_answer: 1988–1996','is_correct':True},'1988–1996','1988-96')==['correct_but_reference_text_absent']
 flags=module.review_flags({'raw':'extracted_final_answer: Reference Name','is_correct':False},'Other Name','Reference Name')
 assert 'judge_extraction_equals_reference_but_absent_from_response' in flags
 assert 'incorrect_but_extracted_answer_matches_reference' in flags


def test_review_note_does_not_resolve_an_outstanding_judge_disagreement():
 rows=[{'case':'one'},{'case':'two','review':{'status':'needs_independent_verdict'}},{'case':'three','review':{'outcome':'verdict_supported'}}]
 assert module.review_counts(rows)=={'unreviewed':1,'needs_independent_verdict':1,'unresolved':2}
