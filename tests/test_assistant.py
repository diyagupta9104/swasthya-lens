import config
import assistant
from engine import parse_report, lookup_result
from retrieval import retrieve_notes


def message(text):
    return {'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}]}


def test_six_rows_and_printed_ranges(report):
    rows = parse_report(report)
    assert len(rows) == 6
    assert rows['Hemoglobin'].status == 'Below report range'
    assert rows['WBC'].status == 'Within report range'


def test_missing_and_reversed_ranges():
    assert parse_report('WBC 7.6 x10^3/uL')['WBC'].status == 'Range missing'
    assert parse_report('WBC 7.6 x10^3/uL 11 - 4')['WBC'].status == 'Range missing'


def test_ocr_merged_spaces_and_prefix_unit():
    assert parse_report('MCV78fL80-100')['MCV'].value == 78
    row = parse_report('WBC (x10^3/uL) 7.6 4 - 11')['WBC']
    assert row.value == 7.6 and row.unit == 'x10^3/uL'


def test_conflicting_duplicates_are_omitted():
    assert 'MCV' not in parse_report('MCV 78 fL 80-100\nMCV 93 fL 80-100')


def test_lookup_missing_marker(report):
    assert 'error' in lookup_result('CRP', parse_report(report))


def test_retrieval_specific_note():
    assert 'CBC-12' in [note['id'] for note in retrieve_notes('Why is my MCV low?')[:2]]


def test_answer_context_matches_report_direction(report):
    rows = parse_report(report)
    notes = assistant._context_notes('Why is my MCV low?', rows, ['MCV'], assistant.DOCUMENTS)
    assert {'CBC-11', 'CBC-12'} <= {note['id'] for note in notes}
    assert 'CBC-13' not in {note['id'] for note in notes}
    raised = parse_report('WBC | 13.8 | x10^3/uL | 4 - 11')
    notes = assistant._context_notes('What does high WBC mean?', raised, ['WBC'], assistant.DOCUMENTS)
    assert {'CBC-07', 'CBC-08'} <= {note['id'] for note in notes}
    assert 'CBC-05' not in {note['id'] for note in notes}


def test_missing_result_and_scope(report):
    assert assistant.answer('What is my CRP value?', report)['mode'] == 'Missing result'
    assert assistant.answer('What is the weather?', report)['mode'] == 'Scope check'


def test_urgent_routing_needs_no_model(report, monkeypatch):
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Model should not be called')))
    assert assistant.answer('I have chest pain', report)['mode'] == 'Safety route'


def test_followup_keeps_marker_context(report):
    first = assistant.answer('What is my MCV?', report)
    second = assistant.answer('Is that low?', report, focus=first['topics'])
    assert second['topics'] == ['MCV']
    assert '78' in second['content'] and 'Hemoglobin:' not in second['content']


def test_greeting_and_goodbye_do_not_read_out_results(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Small talk should not call the model')))
    for question in ('hii', 'hm fine fine.. bye'):
        reply = assistant.answer(question, report, focus=['Hemoglobin', 'MCV'])
        assert reply['mode'] == 'Conversation'
        assert reply['topics'] == [] and reply['sources'] == []
        assert '11.2' not in reply['content']


def test_cause_question_uses_both_red_cell_markers_and_cause_notes(report):
    question = 'What could be causing my low hemoglobin and small red blood cells, and what further tests might help clarify this?'
    reply = assistant.answer(question, report, focus=['Hemoglobin', 'MCV'])
    assert reply['topics'] == ['Hemoglobin', 'MCV']
    assert {'CBC-19', 'CBC-20'} <= {source['id'] for source in reply['sources']}


def test_bare_and_joined_citations_are_normalized(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: message('MCV is 78 fL R7. Small cells may need review CBC-11CBC-12.'))
    reply = assistant.answer('What does my MCV mean?', report)
    assert reply['mode'] == 'OpenAI + RAG'
    assert '[R7]' in reply['content']
    assert '[CBC-11] [CBC-12]' in reply['content']


def test_local_booking_and_negation(report):
    assert assistant.answer('Please book a demo consultation', report)['booking']['id'].startswith('DEMO-')
    count = len(assistant.CONSULTATIONS)
    assert assistant.answer('Do not book a consultation', report)['booking'] is None
    assert len(assistant.CONSULTATIONS) == count


def test_openai_function_call_roundtrip(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    calls = []
    responses = iter([
        {'output': [{'type': 'function_call', 'call_id': 'lookup-1', 'name': 'lookup_result', 'arguments': '{"marker":"MCV"}'}]},
        message('MCV is 78 fL, below the printed interval [R7].'),
    ])
    def fake(*args, **kwargs):
        calls.append(args[1].copy())
        return next(responses)
    monkeypatch.setattr(assistant, 'respond', fake)
    reply = assistant.answer('What is my MCV?', report)
    assert reply['mode'] == 'OpenAI + tools'
    assert reply['trace'][0]['output']['value'] == 78
    assert any(item.get('type') == 'function_call_output' for item in calls[1])


def test_model_invented_value_falls_back(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: message('MCV is 98 fL [R7].'))
    assert assistant.answer('What is my MCV?', report)['mode'] == 'Grounding fallback'


def test_model_invented_citation_falls_back(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: message('MCV is 78 fL [R999].'))
    assert assistant.answer('What is my MCV?', report)['mode'] == 'Grounding fallback'


def test_unsupported_cause_falls_back(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: message('Your low MCV is caused by iron deficiency [R7] [CBC-12].'))
    assert assistant.answer('Why is my MCV low?', report)['mode'] == 'Grounding fallback'


def test_unsupported_specific_test_falls_back(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: message('Your MCV is 78 fL [R7]. Ask for ferritin or iron studies [CBC-12].'))
    assert assistant.answer('What further tests?', report, focus=['MCV'])['mode'] == 'Grounding fallback'


def test_grouped_citations_normalized_before_number_check(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: message('MCV is 78 fL [R7]. Average cell size is smaller [CBC-11, CBC-12].'))
    reply = assistant.answer('Why is my MCV low?', report)
    assert reply['mode'] == 'OpenAI + RAG'
    assert '[CBC-11] [CBC-12]' in reply['content']


def test_unknown_grouped_citation_still_rejected(report, monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    monkeypatch.setattr(assistant, 'respond', lambda *args, **kwargs: message('MCV is 78 fL [R7, CBC-999].'))
    assert assistant.answer('What is my MCV?', report)['mode'] == 'Grounding fallback'


def test_provider_failure_stays_usable(report, monkeypatch):
    from provider import ProviderError
    monkeypatch.setattr(config, 'api_key', lambda: 'test-key')
    def fail(*args, **kwargs):
        raise ProviderError('OpenAI quota or rate limit reached')
    monkeypatch.setattr(assistant, 'respond', fail)
    result = assistant.answer('Explain MCV', report)
    assert result['mode'] == 'Local fallback' and '78' in result['content']
    assert 'quota' in result['warning']
