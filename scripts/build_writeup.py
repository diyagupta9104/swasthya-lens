"""Render the five-page creation write-up as a shareable PDF."""
from pathlib import Path

import pymupdf
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'docs' / 'creation_writeup.html'
PDF = ROOT / 'docs' / 'Swasthya_Lens_Creation_Writeup_Diya_Gupta.pdf'

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page()
    page.goto(HTML.as_uri(), wait_until='load')
    page.evaluate("Promise.all(Array.from(document.images, image => image.decode()))")
    page.pdf(path=str(PDF), prefer_css_page_size=True, print_background=True,
             margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'})
    browser.close()

with pymupdf.open(PDF) as document:
    document.set_metadata({
        'title': 'Swasthya Lens - Creation Write-up',
        'author': 'Diya Gupta',
        'subject': 'Problem, pdfmark-ocr package, design, verification, and limits',
        'keywords': 'Swasthya Lens, pdfmark-ocr, CBC, RAG, Diya Gupta',
    })
    metadata_pdf = PDF.with_suffix('.metadata.pdf')
    document.save(metadata_pdf)
metadata_pdf.replace(PDF)
print(PDF)
