"""Small opt-in integration check. Uses synthetic report data only."""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from assistant import answer
import assistant
from provider import output_text

raw_answers = []
original_respond = assistant.respond
def capture_response(*args, **kwargs):
    response = original_respond(*args, **kwargs)
    text = output_text(response)
    if text:
        raw_answers.append(text)
    return response
assistant.respond = capture_response

report = (ROOT / 'sample_report.txt').read_text(encoding='utf-8')
history, focus, results = [], [], []
cases = [('What does my MCV mean?', 'English'), ('Is that result high or low?', 'English'),
         ('Explain my hemoglobin result in Hindi.', 'Hindi'), ('Please book a demo consultation.', 'English')]
for question, language in cases:
    result = answer(question, report, history, focus, language)
    history.extend([{'role': 'user', 'content': question}, {'role': 'assistant', 'content': result['content']}])
    focus = result['topics']
    record = {'question': question, 'language': language, 'mode': result['mode'], 'content': result['content'],
              'retrieval': result['retrieval'], 'latency_ms': result['latency_ms'],
              'tools': [item['tool'] for item in result['trace']], 'source_ids': [item['id'] for item in result['sources']],
              'warning': result['warning']}
    results.append(record)
    if result['mode'] == 'Grounding fallback' and raw_answers:
        record['rejected_model_answer'] = raw_answers[-1]
    print(json.dumps(record, ensure_ascii=True), flush=True)
(ROOT / 'docs').mkdir(exist_ok=True)
(ROOT / 'docs' / 'live-verification.json').write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'synthetic_data_only': True, 'cases': results}, ensure_ascii=False, indent=2), encoding='utf-8')
if any(not result['mode'].startswith('OpenAI') for result in results):
    raise SystemExit('At least one live case used a fallback. Review the saved evidence.')
