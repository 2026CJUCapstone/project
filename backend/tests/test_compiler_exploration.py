import pytest

from app.services.compiler_graphs import build_bpp_ssa_graph_from_json


def _source(*names: str) -> str:
    return '\n'.join(f'func {name}() -> u64 {{ return 0; }}' for name in names)


def _graph(functions: list[dict]) -> dict:
    result = build_bpp_ssa_graph_from_json({'ssa': {'functions': functions}}, _source(*(item['name'] for item in functions)))
    assert result is not None
    return result


def test_structured_value_flow_is_whitelisted_and_remains_scoped_to_each_function():
    graph = _graph([
        {
            'name': 'main',
            'blocks': [{'id': 'b0', 'instructions': [{
                'id': 'main-add',
                'opcode': 'add',
                'result': {'kind': 'reg', 'id': 99},
                'operands': [{'kind': 'reg', 'id': 88}],
                'valueFlow': {
                    'version': 1,
                    'definitions': ['r1', 'r01', 'r0', 'r10', 'r10', 9],
                    'uses': ['r2', 'r03', 'r0', 'r2', 'pointer'],
                    'complete': True,
                },
            }]}],
        },
        {
            'name': 'helper',
            'blocks': [{'id': 'b0', 'instructions': [{
                'id': 'helper-add',
                'opcode': 'add',
                'valueFlow': {'version': 1, 'definitions': ['r1'], 'uses': ['r2'], 'complete': False},
            }]}],
        },
    ])

    main, helper = graph['blocks']
    assert (main['id'], main['functionId']) == ('main:b0', 'main')
    assert (helper['id'], helper['functionId']) == ('helper:b0', 'helper')
    assert main['instructionDetails'] == [{
        'id': 'main-add', 'opcode': 'add', 'result': 'r1', 'definitions': ['r1', 'r10'],
        'uses': ['r2'], 'complete': True, 'generated': False, 'generatedReason': None,
    }]
    assert helper['instructionDetails'][0]['definitions'] == ['r1']
    assert helper['instructionDetails'][0]['uses'] == ['r2']
    assert helper['instructionDetails'][0]['complete'] is False


@pytest.mark.parametrize('opcode, expects_definition', [
    ('call', True), ('call_ptr', True), ('call_slice_store', False), ('ret_slice_heap', False),
])
def test_legacy_calls_never_turn_opaque_pointer_data_into_register_uses(opcode: str, expects_definition: bool):
    graph = _graph([{
        'name': 'main',
        'blocks': [{'id': 'b0', 'instructions': [{
            'id': f'{opcode}-instruction',
            'opcode': opcode,
            'result': {'kind': 'reg', 'id': 7},
            # For legacy call forms this field can contain a pointer/descriptor,
            # even when its shape resembles a register operand.
            'operands': [{'kind': 'reg', 'id': 41}],
        }]}],
    }])

    detail = graph['blocks'][0]['instructionDetails'][0]
    assert detail['uses'] == []
    assert detail['complete'] is False
    assert detail['definitions'] == (['r7'] if expects_definition else [])


def test_legacy_phi_fallback_preserves_all_typed_incoming_registers():
    graph = _graph([{
        'name': 'main',
        'blocks': [{'id': 'join', 'instructions': [{
            'id': 'phi-1',
            'opcode': 'phi',
            'result': {'kind': 'reg', 'id': 9},
            'operands': [
                {'value': {'kind': 'reg', 'id': 2}},
                {'value': {'kind': 'reg', 'id': 3}},
                {'value': {'kind': 'reg', 'id': 2}},
                {'value': {'kind': 'const', 'id': 4}},
            ],
        }]}],
    }])

    detail = graph['blocks'][0]['instructionDetails'][0]
    assert detail['definitions'] == ['r9']
    assert detail['uses'] == ['r2', 'r3']
    assert detail['complete'] is True


def test_optimization_summaries_keep_only_versioned_function_counter_evidence():
    graph = _graph([
        {
            'name': 'main',
            'optimizationSummary': {
                'version': 1,
                'scope': 'function',
                'level': 1,
                'constantOperands': 4,
                'constantBranches': True,
                'commonExpressions': -1,
                'unusedCopies': 1_000_000_001,
                'deadStores': 0,
                'unreachableBlocks': 3.5,
                'simplifiedPhi': '2',
                'algebraicSimplifications': 7,
                'unrecognizedCounter': 11,
            },
            'blocks': [],
        },
        {
            'name': 'helper',
            'optimizationSummary': {'version': 2, 'scope': 'function', 'level': 1, 'constantOperands': 5},
            'blocks': [],
        },
    ])

    assert graph['optimizationSummaries'] == [{
        'functionId': 'main',
        'functionName': 'main',
        'level': 1,
        'scope': 'function',
        'evidence': 'compiler-counters-v1',
        'counters': {'constantOperands': 4, 'deadStores': 0, 'algebraicSimplifications': 7},
    }]
