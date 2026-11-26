"""HTTP API and report sessions for Swasthya Lens."""
from __future__ import annotations

import tempfile
import threading
import time
import uuid
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from assistant import METRICS, answer, _demo_consultation
from engine import ROOT, parse_report
from retrieval import DOCUMENTS

app = FastAPI(title='Swasthya Lens', version='2.0.0', description='Evidence-grounded CBC report companion')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
SESSIONS: dict[str, dict] = {}
SESSION_TTL = 3600
MAX_UPLOAD = 8 * 1024 * 1024
OCR_LOCK = threading.Lock()
SAMPLE_REPORTS = [
    {'id': 'low-red-cell', 'name': 'Aarohi', 'title': 'Low red cell indices', 'description': 'Hemoglobin, hematocrit and MCV sit below the intervals printed on this synthetic CBC.', 'kind': 'Text report', 'accent': 'amber', 'file': 'sample_report.txt', 'question': 'What do my low hemoglobin and MCV mean?'},
    {'id': 'raised-wbc', 'name': 'Kabir', 'title': 'Raised white cell count', 'description': 'Explore one WBC flag while the other supported CBC markers remain in range.', 'kind': 'Text report', 'accent': 'sky', 'file': 'sample_reports/neutrophil_pattern.txt', 'question': 'What can a high WBC result mean?'},
    {'id': 'low-platelets', 'name': 'Meera', 'title': 'Low platelet count', 'description': 'See how the assistant handles a platelet result below the report interval.', 'kind': 'Text report', 'accent': 'rose', 'file': 'sample_reports/low_platelets.txt', 'question': 'What should I ask my clinician about low platelets?'},
    {'id': 'within-range', 'name': 'Aarav', 'title': 'Within printed ranges', 'description': 'A full synthetic CBC without an out-of-range flag. Practice asking follow-up questions.', 'kind': 'Text report', 'accent': 'mint', 'file': 'sample_reports/within_range.txt', 'question': 'Does this report show any results outside its printed ranges?'},
    {'id': 'scanned-pdf', 'name': 'OCR practice', 'title': 'Scanned PDF', 'description': 'Run the included image-based PDF through your pdfmark-ocr package, then review the extracted rows.', 'kind': 'Scanned PDF · OCR', 'accent': 'violet', 'file': 'sample_scanned.pdf', 'question': 'Which values were extracted from this scan?'},
]


class TextReport(BaseModel):
    text: str = Field(min_length=4, max_length=100_000)


class ChatRequest(BaseModel):
    session_id: str
    question: str = Field(min_length=2, max_length=1000)
    language: Literal['English', 'Hindi'] = 'English'


class FeedbackRequest(BaseModel):
    query_id: str
    rating: Literal['helpful', 'not_helpful']


def _session(session_id: str) -> dict:
    session = SESSIONS.get(session_id)
    if not session or time.time() - session['created'] > SESSION_TTL:
        SESSIONS.pop(session_id, None)
        raise HTTPException(404, 'Report session expired. Please load your report again.')
    return session


def _payload(session_id: str, session: dict) -> dict:
    rows = parse_report(session['text'])
    return {'session_id': session_id, 'extraction': session['extraction'], 'extraction_ms': session['extraction_ms'],
            'sample': session.get('sample'),
            'reviewed': session['reviewed'], 'text': session['text'], 'row_count': len(rows),
            'results': [{'marker': row.marker, 'value': row.value, 'unit': row.unit, 'low': row.low, 'high': row.high,
                         'range': row.range_label, 'status': row.status, 'line': row.line_number, 'raw_line': row.raw_line}
                        for row in rows.values()],
            'warnings': ['Check every displayed value and interval against the original. Unsupported or conflicting duplicate rows are omitted.']}


def _store(text: str, extraction: str, reviewed: bool = False, elapsed: int = 0, sample: dict | None = None) -> dict:
    if not text.strip():
        raise HTTPException(422, 'No readable text was found. Try a clearer scan or paste the report text.')
    for token, session in list(SESSIONS.items()):
        if time.time() - session['created'] > SESSION_TTL:
            SESSIONS.pop(token, None)
    if len(SESSIONS) >= 100:
        raise HTTPException(503, 'The local demo has reached its session limit. Clear an old report or restart the server.')
    session_id = uuid.uuid4().hex
    session = {'text': text[:100_000], 'extraction': extraction, 'extraction_ms': elapsed, 'reviewed': reviewed,
               'sample': {key: sample[key] for key in ('id', 'name', 'title', 'question')} if sample else None,
               'created': time.time(), 'history': [], 'focus': [], 'lock': threading.Lock()}
    SESSIONS[session_id] = session
    return _payload(session_id, session)


def _ocr_pdf(data: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix='swasthya-') as folder:
        pdf, output = Path(folder) / 'report.pdf', Path(folder) / 'report.md'
        pdf.write_bytes(data)
        # OCR's ONNX models are large. Run them outside the web process so their
        # memory is released after each report, including after AI chat.
        environment = os.environ.copy()
        environment.pop('OPENAI_API_KEY', None)
        environment.pop('Open_ai_api_key', None)
        environment.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        with OCR_LOCK:
            try:
                result = subprocess.run([sys.executable, str(ROOT / 'ocr_worker.py'), str(pdf), str(output)],
                                        capture_output=True, text=True, timeout=90, env=environment)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('OCR took too long. Try a clearer, shorter report.') from exc
        if result.returncode != 0:
            raise ValueError('The PDF could not be read. Try an unlocked, clearer report.')
        return output.read_text(encoding='utf-8')


def _extract(data: bytes, extension: str) -> str:
    if extension in ('.png', '.jpg', '.jpeg'):
        from PIL import Image
        from io import BytesIO
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError('Use a report image smaller than 20 megapixels.')
            converted = BytesIO()
            image.convert('RGB').save(converted, format='PDF', resolution=150)
            data = converted.getvalue()
    return _ocr_pdf(data)


@app.get('/')
def index():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/api/health')
def health():
    return {'ok': True, 'model_enabled': bool(config.api_key()), 'model': config.MODEL,
            'ocr': 'pdfmark-ocr / RapidOCR', 'semantic_enabled': config.SEMANTIC and bool(config.api_key()),
            'knowledge_chunks': len(DOCUMENTS), 'session_ttl_minutes': 60}


@app.post('/api/report/demo')
async def demo_report():
    return await load_sample_report('low-red-cell')


@app.get('/api/reports/samples')
def sample_reports():
    return {'reports': [{key: value for key, value in sample.items() if key != 'file'} for sample in SAMPLE_REPORTS]}


@app.post('/api/report/sample/{sample_id}')
async def load_sample_report(sample_id: str):
    sample = next((item for item in SAMPLE_REPORTS if item['id'] == sample_id), None)
    if sample is None:
        raise HTTPException(404, 'That sample report was not found.')
    source = ROOT / sample['file']
    if sample_id == 'scanned-pdf':
        started = time.perf_counter()
        try:
            text = await run_in_threadpool(_ocr_pdf, source.read_bytes())
        except Exception as exc:
            raise HTTPException(422, 'The sample scan could not be read. Check the OCR installation.') from exc
        return _store(text, 'pdfmark-ocr · local RapidOCR', elapsed=round((time.perf_counter() - started) * 1000), sample=sample)
    return _store(source.read_text(encoding='utf-8'), 'Synthetic demonstration report', reviewed=True, sample=sample)


@app.post('/api/report/text')
def text_report(payload: TextReport):
    return _store(payload.text, 'Pasted report text')


@app.post('/api/report/upload')
async def upload_report(file: UploadFile = File(...)):
    started = time.perf_counter()
    extension = Path(file.filename or '').suffix.lower()
    if extension not in ('.pdf', '.txt', '.png', '.jpg', '.jpeg'):
        raise HTTPException(415, 'Upload a PDF, TXT, PNG or JPG report.')
    data = await file.read(MAX_UPLOAD + 1)
    await file.close()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, 'Please use a file smaller than 8 MB.')
    try:
        if extension == '.txt':
            text, method = data.decode('utf-8-sig'), 'TXT report'
        else:
            if extension == '.pdf' and not data.startswith(b'%PDF-'):
                raise ValueError('This file is not a valid PDF.')
            text = await run_in_threadpool(_extract, data, extension)
            method = 'pdfmark-ocr · local RapidOCR'
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, 'Could not read that file. Try an unlocked PDF, a clearer image, or paste its text.') from exc
    return _store(text, method, elapsed=round((time.perf_counter() - started) * 1000))


@app.post('/api/report/{session_id}/review')
def review_report(session_id: str, payload: TextReport):
    session = _session(session_id)
    with session['lock']:
        if not parse_report(payload.text):
            raise HTTPException(422, 'No supported CBC rows found. Use: Hemoglobin | 11.2 | g/dL | 12.0 - 15.5')
        session.update(text=payload.text, reviewed=True, history=[], focus=[])
        return _payload(session_id, session)


@app.delete('/api/report/{session_id}')
def clear_report(session_id: str):
    SESSIONS.pop(session_id, None)
    return {'cleared': True}


def _chat(session: dict, payload: ChatRequest):
    with session['lock']:
        result = answer(payload.question.strip(), session['text'], session['history'], session['focus'], payload.language)
        session['history'].extend([{'role': 'user', 'content': payload.question}, {'role': 'assistant', 'content': result['content']}])
        session['history'] = session['history'][-8:]
        if result['topics']:
            session['focus'] = result['topics']
        return result


@app.post('/api/chat')
async def chat(payload: ChatRequest):
    session = _session(payload.session_id)
    if not session['reviewed']:
        raise HTTPException(409, 'Review and confirm the extracted values before starting the chat.')
    return await run_in_threadpool(_chat, session, payload)


@app.post('/api/feedback')
def feedback(payload: FeedbackRequest):
    metric = next((item for item in METRICS if item['query_id'] == payload.query_id), None)
    if metric is None:
        raise HTTPException(404, 'This response is no longer in the local metrics window.')
    metric['feedback'] = payload.rating
    return {'saved': True}


@app.get('/api/metrics')
def metrics():
    values = sorted(item['latency_ms'] for item in METRICS)
    return {'queries': len(METRICS), 'mean_latency_ms': round(sum(values) / len(values)) if values else 0,
            'p95_latency_ms': values[min(len(values) - 1, int(len(values) * .95))] if values else 0,
            'helpful': sum(item['feedback'] == 'helpful' for item in METRICS),
            'fallbacks': sum('fallback' in item['mode'].lower() for item in METRICS), 'recent': METRICS[-8:][::-1]}


@app.get('/api/report/{session_id}/brief')
def consultation_brief(session_id: str):
    import pymupdf
    session = _session(session_id)
    if not session['reviewed']:
        raise HTTPException(409, 'Confirm the extracted values first.')
    rows = parse_report(session['text'])
    document = pymupdf.open()
    page = document.new_page()
    page.draw_rect(pymupdf.Rect(0, 0, 595, 120), color=None, fill=(.05, .24, .22))
    page.insert_text((40, 56), 'Swasthya Lens', fontsize=25, color=(1, 1, 1))
    page.insert_text((40, 86), 'Your CBC consultation brief', fontsize=13, color=(.75, .9, .8))
    body = 'REPORT VALUES\n\n'
    for row in rows.values():
        interval = f'{row.low:g} - {row.high:g}' if row.low is not None else 'not printed'
        body += f'{row.marker}: {row.value:g} {row.unit}\nReport interval: {interval} | {row.status}\n\n'
    body += 'QUESTIONS FOR YOUR CLINICIAN\n\n'
    body += '- Which findings need follow-up in my situation?\n- Do these results explain my symptoms, or is more context needed?\n- Is a repeat test appropriate, and when?\n\n'
    body += 'This summary repeats reviewed report values. It does not diagnose or recommend treatment. Bring the original report to your consultation.\n\nReference: medlineplus.gov/lab-tests/complete-blood-count-cbc/'
    page.insert_textbox(pymupdf.Rect(40, 145, 555, 810), body, fontsize=10, lineheight=1.35, color=(.1, .2, .18))
    data = document.tobytes()
    document.close()
    return Response(data, media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename="swasthya-consultation-brief.pdf"'})
