#!/usr/bin/env python3
"""Run QUEST with an optional GAIA answer-format prompt, without editing QUEST inference."""
import argparse
import hashlib
import os
from pathlib import Path
import runpy
import sys

INFERENCE = Path(__file__).resolve().parents[2] / 'inference'
ENTRY = INFERENCE / 'run_multi_react.py'
GAIA_NAME = 'SYSTEM_PROMPT_GAIA_FORMAT_PLUGIN'
GAIA_ADDENDUM = '''# GAIA final-answer format
For GAIA questions, put only the final answer inside <answer></answer>.
Use a number, a short string, or a comma-separated list as requested.
Do not include explanations, citations, or extra wording inside the tags.
Follow any specific formatting instructions in the question.
'''

def install():
    previous = os.environ.get('SYSTEM_PROMPT_NAME', '').strip()
    if previous not in ('', 'SYSTEM_PROMPT', GAIA_NAME):
        raise RuntimeError('GAIA plugin cannot override a different SYSTEM_PROMPT_NAME')
    import prompt
    marker = '\nCurrent date: '
    original = prompt.SYSTEM_PROMPT
    if original.count(marker) != 1:
        raise RuntimeError('Unexpected upstream SYSTEM_PROMPT date marker; refusing to modify prompt')
    setattr(prompt, GAIA_NAME, original.replace(marker, '\n' + GAIA_ADDENDUM + marker, 1))
    os.environ['SYSTEM_PROMPT_NAME'] = GAIA_NAME

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gaia-format', action='store_true', help='enable the GAIA answer-format addendum')
    parser.add_argument('--check', action='store_true', help='verify prompt wiring only, do not run inference')
    args, rest = parser.parse_known_args()
    if rest and rest[0] == '--': rest = rest[1:]
    sys.path.insert(0, str(INFERENCE))
    if args.gaia_format: install()
    if args.check:
        import react_agent
        rendered = react_agent.build_system_prompt(react_agent.PYTHON_TOOL_ENABLED)
        enabled = GAIA_ADDENDUM in rendered
        if enabled != args.gaia_format: raise RuntimeError('Prompt activation mismatch')
        print('gaia_format_enabled=' + str(enabled).lower())
        print('system_prompt_sha256=' + hashlib.sha256(rendered.encode()).hexdigest())
        return
    print('gaia_format_enabled=' + str(args.gaia_format).lower(), flush=True)
    sys.argv = [str(ENTRY), *rest]
    runpy.run_path(str(ENTRY), run_name='__main__')

if __name__ == '__main__': main()
