"""Run the offline suite, including a real scanned-PDF OCR check."""
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-q', 'tests'], cwd=Path(__file__).resolve().parent))
