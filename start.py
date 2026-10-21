#!/usr/bin/env python3
"""Start the prebuilt application with Python alone."""
import sys
from pathlib import Path


def main():
    if sys.version_info < (3, 10):
        sys.exit('ExpObserver requires Python 3.10 or newer. No Node.js or pip packages are needed.')
    root = Path(__file__).resolve().parent
    if not (root / 'dist' / 'index.html').is_file():
        sys.exit('Download the ready-to-run exp-observer.zip from GitHub Releases. '
                 'To build a source checkout instead, run: npm ci && npm run build')
    from backend.server import main as serve
    serve(['--open', *sys.argv[1:]])


if __name__ == '__main__':
    main()