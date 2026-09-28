"""Deterministic whole-submission judging within one durable execution slot."""
from app.services.compile_queue import classify_grading_result, classify_compile_stage_result
from app.models.judge_test_manifest import has_stored_cases,is_reference_case


async def judge_code(runner, payload, *, contest=False, load_case=None):
    contract = payload.get('judge_contract')
    if not isinstance(contract,dict) or contract.get('kind')!='measured-v1':
        raise RuntimeError('A graded execution requires an exact measured judge contract')
    references=has_stored_cases(payload.get('sample',[]),payload.get('hidden',[]))
    if references and (not isinstance(contract,dict) or contract.get('kind')!='measured-v1' or load_case is None):
        raise RuntimeError('Stored tests require the measured judge and a trusted case loader')
    if not hasattr(runner,'measured_submission'):
        raise RuntimeError('The measured judge supervisor is not available')
    async with runner.measured_submission(payload) as measured:
        from app.services.judge_metrics import JudgeMetrics
        metrics=JudgeMetrics(payload)
        result=await _judge_cases(measured,payload,contest=contest,metrics=metrics,load_case=load_case)
        result['_resource_report']=metrics.finish()
        return result


async def _judge_cases(runner,payload,*,contest,metrics=None,load_case=None):
    sample,hidden=payload.get('sample',[]),payload.get('hidden',[])
    if not sample and not hidden:
        return {'verdict':'system_error', 'status':'Rejected', 'details':[],
                'sample_total_cases':0, 'sample_passed_cases':0, 'grading_completed':False, 'grading_passed':False}
    code, language = payload['code'], payload['language']
    compiled = await runner._execute(mode='compile', source_code=code, language=language)
    verdict = classify_compile_stage_result(compiled)
    if metrics is not None: metrics.add(compiled,phase='compile')
    if verdict != 'compile_success':
        return {'verdict':verdict, 'status':'Rejected', 'details':[],
                'sample_total_cases':len(sample), 'sample_passed_cases':0, 'grading_completed':False, 'grading_passed':False}

    passed, hidden_passed, details, first_failure = 0, 0, [], None
    # A per-process stdout cap does not bound the sum of 200 sample outputs.
    # Verdicts use complete bounded runner output; public diagnostics have a
    # separate whole-submission UTF-8 budget before the durable JSON is stored.
    detail_budget = 262_144
    def visible_text(value):
        nonlocal detail_budget
        encoded = str(value).encode('utf-8')
        kept = encoded[:detail_budget].decode('utf-8', errors='ignore')
        detail_budget -= len(kept.encode('utf-8'))
        return kept
    for phase, cases in (('sample',sample), ('grading',hidden)):
        if phase == 'grading' and passed != len(sample):
            break
        for index, case in enumerate(cases, 1):
            case_data=await load_case(case) if is_reference_case(case) else case
            expected = case_data.get('expected_output', case_data.get('expectedOutput','')).strip()
            result = await runner.run(source_code=code, language=language, stdin=case_data.get('input',''))
            verdict = classify_grading_result(result, expected)
            if metrics is not None: metrics.add(result,phase=phase,index=index,verdict=verdict)
            if verdict == 'accepted':
                if phase == 'sample': passed += 1
                else: hidden_passed += 1
            elif first_failure is None:
                first_failure = verdict
            # Never retain hidden inputs, output, or diagnostics in the result.
            if phase == 'sample' and not contest:
                status = 'Correct' if verdict == 'accepted' else 'Wrong' if verdict == 'wrong_answer' else 'Error'
                details.append({'case_number':index, 'phase':phase, 'is_visible':True, 'status':status,
                    'verdict':verdict, 'input':visible_text(case.get('input','')), 'expected':visible_text(expected),
                    'actual':visible_text(result.get('stderr','') if status == 'Error' else result.get('stdout','').strip())})
            del case_data,expected  # Release this decoded case before loading the next.
            if contest and verdict != 'accepted':
                return {'verdict':verdict}
    completed = passed == len(sample)
    accepted = completed and hidden_passed == len(hidden)
    return {'verdict':'accepted' if accepted else first_failure or 'wrong_answer',
            'status':'Accepted' if accepted else 'Rejected' if completed else 'SampleFailed',
            'sample_total_cases':len(sample), 'sample_passed_cases':passed,
            'grading_completed':completed, 'grading_passed':accepted, 'details':details}
