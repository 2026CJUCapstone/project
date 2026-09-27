"""Offline measurement harness checks. No Docker/network access."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT))
import verify_freshman_measurements as probe
from app.services.judge_metrics import report_identity
from tests.test_measured_judge import payload_fixture,report_fixture


def accepted_result():
    payload=payload_fixture()
    compile_phase={**report_fixture(),'phase':'compile'}
    report=dict(version=1,identity=report_identity(payload),compile=compile_phase,
        cases=[dict(phase=phase,index=1,verdict='accepted',usage=report_fixture()) for phase in ('sample','grading')])
    return payload,dict(verdict='accepted',_resource_report=report)


def test_reference_result_requires_every_case_once():
    payload,result=accepted_result()
    assert len(probe.validate_reference_result(result,payload,['compile','case1','case2']))==3
    with pytest.raises(ValueError): probe.validate_reference_result(result,payload,['compile','case1','case1'])
    with pytest.raises(ValueError): probe.validate_reference_result(result,payload,['compile','case1','case2','extra'])
    result['_resource_report']['cases'].pop()
    with pytest.raises(ValueError): probe.validate_reference_result(result,payload,['compile','case1'])


@pytest.mark.parametrize('field,value',[('exitCode',137),('failureReason','time_limit_exceeded'),('oomKills',1),('treeReaped',False)])
def test_clean_verdict_requires_clean_phases(field,value):
    payload,result=accepted_result()
    result['_resource_report']['cases'][0]['usage'][field]=value
    with pytest.raises(ValueError): probe.validate_reference_result(result,payload,['compile','case1','case2'])


def test_wrong_case_cannot_be_hidden_by_accepted_summary():
    payload,result=accepted_result()
    result['_resource_report']['cases'][0]['verdict']='wrong_answer'
    with pytest.raises(ValueError): probe.validate_reference_result(result,payload,['compile','case1','case2'])


def test_all_sixty_reference_paths_are_fixed_and_nonempty():
    paths={probe.reference_path(ROOT/'tools/freshman_contest',lang,letter)
           for lang in probe.LANGUAGES for letter in probe.LETTERS}
    assert len(paths)==60
    assert all(path.read_text(encoding='utf-8').strip() for path in paths)
    for lang,letter in [('python','../A'),('../python','A'),('bash','A'),('java','K')]:
        with pytest.raises(ValueError): probe.reference_path(ROOT/'tools/freshman_contest',lang,letter)


def test_missing_and_oversized_source_rejected(tmp_path):
    with pytest.raises(ValueError): probe.reference_path(tmp_path,'python','A')
    folder=tmp_path/'solutions/python';folder.mkdir(parents=True)
    (folder/'A.py').write_bytes(b'x'*65537)
    with pytest.raises(ValueError): probe.reference_path(tmp_path,'python','A')


def test_bpp_diagnostics_preserve_original_and_do_not_replace_references():
    base=ROOT/'tools/freshman_contest'
    rows=probe.bpp_diagnostic_sources(base)
    assert len(rows)==6 and len({r[0] for r in rows})==6
    assert rows[0][1].decode()==probe.reference_path(base,'bpp','G').read_text(encoding='utf-8')
    assert rows[0][2]==[dict(input='1\n1000\n',expected_output='1000\n')]
    assert all(len(code)<65536 and len(cases)==1 for _,code,cases in rows)
    assert 'pointer-parameter' in {r[0] for r in rows}


@pytest.mark.parametrize('letter',probe.LETTERS)
def test_case_manifest_binds_exact_input_and_expected_bytes(letter):
    cases,metadata=probe.cases_for(letter)
    assert len(cases)==len(metadata) and 1<=len(cases)<=10
    assert len({row['name'] for row in metadata})==len(metadata)
    for case,row in zip(cases,metadata):
        input_data=case['input'].encode();expected=case['expected_output'].encode()
        assert row['inputBytes']==len(input_data) and row['inputHash']==probe.sha(input_data)
        assert row['expectedBytes']==len(expected) and row['expectedHash']==probe.sha(expected)
    # Input descriptors are reproducible, not seeded with wall time.
    assert probe.cases_for(letter)[1]==metadata
