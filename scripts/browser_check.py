"""Exercise the real local web app with synthetic data and save screenshots."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
docs = ROOT / 'docs'
docs.mkdir(exist_ok=True)
errors = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1050}, device_scale_factor=1)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8510/', wait_until='networkidle')
    assert page.locator('.sample-card').count() == 5
    page.screenshot(path=str(docs / 'screenshot-home.png'), full_page=True)
    page.click('#demo-button')
    page.wait_for_selector('#chat-section:visible')
    assert page.locator('.result-card').count() == 6
    page.fill('#question-input', 'What does my MCV mean?')
    page.click('#send-button')
    page.wait_for_selector('.thinking', state='detached', timeout=90000)
    answer_mode = page.locator('#answer-mode').inner_text()
    assert answer_mode != 'READY'
    assert page.locator('.citation').count() > 0
    page.locator('.feedback-button').first.click()
    page.wait_for_selector('.feedback-button:disabled')
    with page.expect_download() as download_event:
        page.click('#download-brief')
    download = download_event.value
    assert download.suggested_filename.endswith('.pdf')
    page.screenshot(path=str(docs / 'screenshot-workspace.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
    page.screenshot(path=str(docs / 'screenshot-mobile.png'), full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1050})
    page.click('#nav-new')
    page.wait_for_selector('#upload-section:visible')
    page.locator('.sample-card').nth(2).locator('button').click()
    page.wait_for_selector('#chat-section:visible')
    assert any('Platelets' in text and '105' in text for text in page.locator('.result-card').all_text_contents())
    page.click('#nav-new')
    page.wait_for_selector('#upload-section:visible')
    page.locator('.sample-card').last.locator('button').click()
    page.wait_for_selector('#review-panel:visible', timeout=30000)
    assert not page.locator('#chat-section').is_visible()
    page.click('#confirm-review')
    page.wait_for_selector('#chat-section:visible')
    assert page.locator('.result-card').count() == 3
    assert not errors, errors
    browser.close()
print(json.dumps({'browser': 'Chrome', 'desktop': '1440x1050', 'mobile': '390x844', 'answer_mode': answer_mode, 'checks': ['five report choices', 'CBC answer', 'citations', 'feedback', 'PDF download', 'mobile overflow', 'platelet sample', 'scanned PDF review'], 'javascript_errors': errors}))
