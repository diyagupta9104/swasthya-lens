from fastapi.testclient import TestClient
from server import app, SESSIONS
from engine import parse_report
import pymupdf

client = TestClient(app)


def test_demo_and_local_chat():
    demo = client.post('/api/report/demo').json()
    assert demo['row_count'] == 6 and demo['reviewed']
    response = client.post('/api/chat', json={'session_id': demo['session_id'], 'question': 'What is my MCV?'})
    assert response.status_code == 200
    assert '78' in response.json()['content']


def test_sample_library_opens_distinct_synthetic_cases():
    samples = client.get('/api/reports/samples').json()['reports']
    assert len(samples) == 5
    assert all('file' not in sample for sample in samples)
    expected = {'low-red-cell': ('MCV', 'Below report range'),
                'raised-wbc': ('WBC', 'Above report range'),
                'low-platelets': ('Platelets', 'Below report range'),
                'within-range': ('Hemoglobin', 'Within report range')}
    for sample_id, (marker, status) in expected.items():
        response = client.post(f'/api/report/sample/{sample_id}')
        assert response.status_code == 200
        data = response.json()
        assert data['sample']['id'] == sample_id and data['reviewed']
        assert next(row for row in data['results'] if row['marker'] == marker)['status'] == status
    assert client.post('/api/report/sample/missing').status_code == 404


def test_scanned_sample_requires_value_review():
    response = client.post('/api/report/sample/scanned-pdf')
    assert response.status_code == 200
    data = response.json()
    assert not data['reviewed'] and 'pdfmark-ocr' in data['extraction']
    assert any(row['marker'] == 'MCV' and row['value'] == 78 for row in data['results'])


def test_unreviewed_report_cannot_chat(report):
    token = client.post('/api/report/text', json={'text': report}).json()['session_id']
    assert client.post('/api/chat', json={'session_id': token, 'question': 'Explain MCV'}).status_code == 409
    reviewed = client.post(f'/api/report/{token}/review', json={'text': report.replace('MCV | 78', 'MCV | 82')})
    assert reviewed.status_code == 200
    row = next(row for row in reviewed.json()['results'] if row['marker'] == 'MCV')
    assert row['value'] == 82 and row['status'] == 'Within report range'


def test_clear_report_removes_session():
    token = client.post('/api/report/demo').json()['session_id']
    assert client.delete(f'/api/report/{token}').status_code == 200
    assert token not in SESSIONS
    assert client.post('/api/chat', json={'session_id': token, 'question': 'What is my MCV?'}).status_code == 404


def test_bad_file_and_unknown_file_type():
    assert client.post('/api/report/upload', files={'file': ('x.pdf', b'not a pdf')}).status_code == 422
    assert client.post('/api/report/upload', files={'file': ('x.exe', b'hello')}).status_code == 415


def test_feedback_updates_metrics():
    token = client.post('/api/report/demo').json()['session_id']
    reply = client.post('/api/chat', json={'session_id': token, 'question': 'Explain MCV'}).json()
    assert client.post('/api/feedback', json={'query_id': reply['query_id'], 'rating': 'helpful'}).status_code == 200
    metrics = client.get('/api/metrics').json()
    assert metrics['helpful'] == 1 and metrics['queries'] == 1
    assert 'content' not in metrics['recent'][0]


def test_consultation_pdf_contains_report_values():
    token = client.post('/api/report/demo').json()['session_id']
    response = client.get(f'/api/report/{token}/brief')
    assert response.headers['content-type'] == 'application/pdf'
    with pymupdf.open(stream=response.content, filetype='pdf') as document:
        text = ''.join(page.get_text() for page in document)
    assert '11.2' in text and 'Hemoglobin' in text and 'QUESTIONS FOR YOUR CLINICIAN' in text


def test_expired_session():
    token = client.post('/api/report/demo').json()['session_id']
    SESSIONS[token]['created'] = 0
    assert client.get(f'/api/report/{token}/brief').status_code == 404


def test_health_does_not_expose_key():
    data = client.get('/api/health').json()
    assert 'api_key' not in data and data['model']


def test_scanned_pdf_upload():
    from config import ROOT
    response = client.post('/api/report/upload', files={'file': ('scan.pdf', (ROOT / 'sample_scanned.pdf').read_bytes(), 'application/pdf')})
    assert response.status_code == 200
    data = response.json()
    rows = {row['marker']: row for row in data['results']}
    assert rows['Hemoglobin']['value'] == 11.2
    assert rows['MCV']['value'] == 78 and rows['MCV']['low'] == 80
    assert not data['reviewed'] and 'pdfmark-ocr' in data['extraction']


def test_page_limit():
    document = pymupdf.open()
    for _ in range(11):
        document.new_page()
    data = document.tobytes()
    document.close()
    assert client.post('/api/report/upload', files={'file': ('long.pdf', data)}).status_code == 422
