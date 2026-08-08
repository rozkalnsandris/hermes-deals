from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools' / 'netto_object_component_signature_audit.py'
spec = importlib.util.spec_from_file_location('netto_object_component_signature_audit', TOOL)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def node(node_id: str, node_type: str, x0: float, y0: float, x1: float, y1: float):
    return {
        'node_id': node_id,
        'node_type': node_type,
        'bbox': {'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1},
        'source_area_fraction_inside_cell': 1.0,
    }


def row(cell_id: str, ownership: str, page: int = 1, variant: str = 'single'):
    nodes = [
        node('price-group:g1', 'price_group', 1, 1, 3, 3),
        node('price-anchor:a1', 'price_anchor', 2, 2, 4, 4),
        node('text-block:1', 'text_block', 1, 4, 8, 8),
        node('image:1', 'image', 0, 0, 9, 9),
    ]
    components = [
        {'component_id': 'c001', 'node_ids': [n['node_id'] for n in nodes]},
    ]
    if variant == 'mixed':
        extra = [
            node('price-group:g2', 'price_group', 10, 10, 12, 12),
            node('price-anchor:a2', 'price_anchor', 11, 11, 13, 13),
            node('text-block:2', 'text_block', 10, 13, 18, 18),
        ]
        nodes.extend(extra)
        components.append({'component_id': 'c002', 'node_ids': [n['node_id'] for n in extra]})
    return {
        'cell_id': cell_id,
        'page_number': page,
        'cell_rect_points': [0, 0, 20, 20],
        'nodes': nodes,
        'separator_respecting_components': components,
        'independent_ownership': ownership,
    }


def payload():
    rows = []
    # Exactly the frozen 88/10/2 truth counts expected by the tool.
    for i in range(88):
        rows.append(row(f's{i:03d}', 'single_source', variant='single'))
    mixed_ids = list(MODULE.HARD_MIXED_CANARIES) + [f'm{i:03d}' for i in range(6)]
    for cid in mixed_ids:
        rows.append(row(cid, 'mixed_source', variant='mixed'))
    rows.append(row('x001', 'excluded_control', variant='single'))
    rows.append(row('x002', 'excluded_control', variant='single'))
    return {
        'schema_version': 1,
        'strategy': MODULE.SOURCE_STRATEGY,
        'cell_count': 100,
        'fixture_page_count': 17,
        'image_binary_retained': False,
        'ocr_used': False,
        'classification_performed': False,
        'parser_behavior_changed': False,
        'review_only': True,
        'promotion_ready': False,
        'database_write_performed': False,
        'deployment_performed': False,
        'automatic_approval_enabled': False,
        'automatic_publish_enabled': False,
        'rows': rows,
    }


def test_tool_is_syntax_valid_and_has_read_only_contract():
    subprocess.run(['python3', '-m', 'py_compile', str(TOOL)], check=True)
    source = TOOL.read_text(encoding='utf-8')
    assert MODULE.TRUTH_USE_CONTRACT in source
    assert 'classification_performed": False' in source
    assert 'parser_behavior_changed": False' in source
    assert 'promotion_ready": False' in source
    assert 'database_write_performed": False' in source
    assert 'review_write_performed": False' in source
    assert 'deployment_performed": False' in source
    assert 'sklearn' not in source
    assert 'ocr' in source.lower()


def test_signature_builder_rejects_truth_and_freezes_component_semantics():
    raw = row('cell-1', 'mixed_source', variant='mixed')
    try:
        MODULE.freeze_cell_signature(raw)
    except MODULE.NettoObjectComponentSignatureAuditError as exc:
        assert 'ownership truth reached signature construction' in str(exc)
    else:
        raise AssertionError('truth-bearing row must be rejected')

    frozen = MODULE.freeze_cell_signature(MODULE._source_only_row(raw))
    sig = frozen['component_signature']
    assert sig == {
        'separator_component_count': 2,
        'complete_commercial_component_count': 2,
        'full_commercial_component_count': 1,
        'nonprice_fragment_component_count': 0,
        'image_text_nonprice_component_count': 0,
        'orphan_price_component_count': 0,
        'multi_price_group_component_count': 0,
        'max_price_groups_per_component': 1,
        'max_component_node_count': 4,
        'second_largest_component_node_count': 3,
    }
    assert [component['component_id'] for component in frozen['components']] == ['c001', 'c002']
    assert frozen['components'][0]['full_commercial_component'] is True
    assert frozen['components'][1]['complete_commercial_component'] is True
    assert frozen['components'][1]['full_commercial_component'] is False


def test_frozen_signature_digest_is_independent_of_truth_labels():
    source = payload()
    first = MODULE.freeze_source_signatures(source)
    first_digest = MODULE._sha256(first)

    changed = copy.deepcopy(source)
    # Change truth labels only; do not call full replay because the 88/10/2 count contract would then reject.
    changed['rows'][0]['independent_ownership'] = 'mixed_source'
    changed['rows'][88]['independent_ownership'] = 'single_source'
    second = MODULE.freeze_source_signatures(changed)
    second_digest = MODULE._sha256(second)

    assert first == second
    assert first_digest == second_digest


def test_full_replay_reports_truth_only_after_signature_freeze():
    result = MODULE.replay_component_signature_audit(payload())
    assert result['source_cell_count'] == 100
    assert result['truth_use_contract'] == MODULE.TRUTH_USE_CONTRACT
    assert result['independent_ownership_counts'] == {
        'single_source': 88,
        'mixed_source': 10,
        'excluded_control': 2,
    }
    assert result['classification_performed'] is False
    assert result['parser_behavior_changed'] is False
    assert result['review_only'] is True
    assert result['promotion_ready'] is False
    assert set(result['hard_mixed_canaries']) == set(MODULE.HARD_MIXED_CANARIES)
    assert result['by_independent_ownership']['mixed_source']['cell_count'] == 10
    mixed_hist = result['by_independent_ownership']['mixed_source']['metric_distributions'][
        'separator_component_count'
    ]['histogram']
    assert mixed_hist == {'2': 10}


def test_unsafe_source_graph_fails_closed():
    source = payload()
    source['classification_performed'] = True
    try:
        MODULE.replay_component_signature_audit(source)
    except MODULE.NettoObjectComponentSignatureAuditError as exc:
        assert 'classification_performed=True' in str(exc)
    else:
        raise AssertionError('unsafe source graph must fail closed')


def test_cli_is_deterministic(tmp_path: Path):
    src = tmp_path / 'graph.json'
    out1 = tmp_path / 'out1.json'
    out2 = tmp_path / 'out2.json'
    src.write_text(json.dumps(payload(), sort_keys=True), encoding='utf-8')

    subprocess.run(['python3', str(TOOL), '--object-graph', str(src), '--output', str(out1)], check=True)
    subprocess.run(['python3', str(TOOL), '--object-graph', str(src), '--output', str(out2)], check=True)
    assert out1.read_bytes() == out2.read_bytes()
