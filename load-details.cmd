@echo off
rem Read product.md + target.md into the tool's saved configuration.
rem Edit those two files, then double-click this (or run it from a terminal).
cd /d "%~dp0"
".venv\Scripts\python.exe" -c "import sys, django; django.setup(); from openoutreach.config.models import SiteConfig; from pathlib import Path; c = SiteConfig.load(); c.product_docs = Path('product.md').read_text(encoding='utf-8'); c.campaign_target = Path('target.md').read_text(encoding='utf-8'); c.save(); print('Saved product + target details. Current status:');" 2>&1
".venv\Scripts\openoutreach.exe" status
pause
