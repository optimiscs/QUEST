"""The workspace summary must not expose files outside its site root."""
import importlib.util
import json
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'web/serve.py'
spec = importlib.util.spec_from_file_location('quest_web_serve', source)
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


def test_status_counts_stopped_and_unscored_cases(tmp_path):
    site = tmp_path / 'site'
    (site / 'datasets').mkdir(parents=True)
    (site / 'datasets/index.json').write_text(json.dumps({'datasets': [{'id': 'run', 'lifecycleOverride': 'stopped'}]}))
    target = site / 'datasets/run/traces.json'
    target.parent.mkdir()
    target.write_text(json.dumps({'cases': [{'correct': True}, {'correct': False}, {'correct': None}, {'inProgress': True}]}))
    counts = viewer.build_workspace_status(site)['datasets']['run']
    assert counts == {'total': 4, 'pass': 1, 'fail': 1, 'error': 1, 'running': 0, 'stopped': 1}


def test_status_refuses_paths_outside_site_including_symlinks(tmp_path):
    site = tmp_path / 'site'
    (site / 'datasets').mkdir(parents=True)
    external = tmp_path / 'outside.json'
    external.write_text(json.dumps({'cases': [{'correct': True}]}))
    (site / 'datasets/link.json').symlink_to(external)
    (site / 'datasets/index.json').write_text(json.dumps({'datasets': [
        {'id': 'traversal', 'data': '../outside.json'},
        {'id': 'symlink', 'data': 'datasets/link.json'},
    ]}))
    assert viewer.build_workspace_status(site)['datasets'] == {}
