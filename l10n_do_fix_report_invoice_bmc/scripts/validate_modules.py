#!/usr/bin/env python3
"""Static validation for WebPOS BMC modules (no Odoo runtime required)."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    ROOT.parent / 'l10n_do_webpos_fe_base',
    ROOT,
]

errors = []

for module in MODULES:
    manifest = module / '__manifest__.py'
    if not manifest.exists():
        errors.append(f'Missing manifest: {manifest}')
        continue
    try:
        ast.literal_eval(manifest.read_text())
    except SyntaxError as exc:
        errors.append(f'Invalid manifest {manifest}: {exc}')

    for py_file in module.rglob('*.py'):
        if '__pycache__' in py_file.parts:
            continue
        try:
            ast.parse(py_file.read_text())
        except SyntaxError as exc:
            errors.append(f'Syntax error {py_file}: {exc}')

    dead = [
        module / 'utils',
        module / 'models' / 'account_edi_format.py',
        module / 'models' / 'webpos_document.py',
    ]
    for path in dead:
        if path.exists():
            errors.append(f'Obsolete path still present: {path}')

required = [
    ROOT / 'data' / 'l10n_latam.document.type.csv',
    ROOT.parent / 'l10n_do_webpos_fe_base' / 'data' / 'ir_cron_webpos_followup.xml',
    ROOT.parent / 'l10n_do_webpos_fe_base' / 'models' / 'account_move_inherit.py',
]
for path in required:
    if not path.exists():
        errors.append(f'Missing required file: {path}')

if errors:
    print('VALIDATION FAILED:')
    for err in errors:
        print(' -', err)
    sys.exit(1)

print('Static validation OK for', len(MODULES), 'modules')
