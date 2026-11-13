"""The real-provider probe must not report success without its evidence."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'material_voice_probe', Path(__file__).resolve().parents[2] / 'web/e2e/material_voice_probe.py'
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def report():
    return {
        'material': {'section_id': 'sec-ecd16baf9e4fee44'},
        'fetched': {'meta_status': 200, 'has_marker': True, 'visible_image_count': 20, 'img_http_200': 12},
        'tool_messages': ['tools executed: search_materials',
                          'board rpc board.show b1 acknowledged=True', 'tools executed: show_material'],
        'ended_cleanly': True,
    }


def test_probe_requires_real_material_and_logged_tools():
    valid = report()
    assert probe.evidence_failures(valid, [{'rms': 0.1}], []) == []
    valid['material'] = {}
    valid['tool_messages'] = []
    failures = probe.evidence_failures(valid, [{'rms': 0.1}], [])
    assert 'No material was shown' in failures
    assert 'No real tool execution logged: search_materials' in failures
    assert 'No real browser acknowledgement logged' in failures


def test_probe_rejects_silent_or_broken_browser_run():
    failures = probe.evidence_failures(report(), [{'rms': 0.0}], ['page failed'])
    assert 'No audible tutor audio measured' in failures
    assert 'Browser errors occurred' in failures
