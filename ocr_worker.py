"""One-report OCR worker, isolated from the web process's memory and API key."""
import os
import sys
from unittest.mock import patch

import pymupdf
from pdf2md_ocr import stitch_full_pdf


def main() -> int:
    source, output = sys.argv[1:3]
    with pymupdf.open(source) as document:
        if document.is_encrypted or len(document) > 10:
            return 2
    # pdfmark-ocr sizes RapidOCR from host CPUs. The free Render instance sees
    # eight CPUs despite having only a small share, so use one ONNX thread.
    with patch.object(os, 'cpu_count', return_value=1):
        markdown, _ = stitch_full_pdf(source, output, engine='rapidocr', workers=1,
                                      max_dim=1100, render_dpi=130, page_ocr='auto')
    return 0 if markdown and markdown.strip() else 2


if __name__ == '__main__':
    sys.exit(main())
