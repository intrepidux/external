#!/usr/bin/env python3
"""Odoo shell: audit WebPOS taxes (does NOT auto-verify).

Usage:
    exec(open('custom/bmc/kvillar93/bmcargo_vbs/l10n_do_fix_report_invoice_bmc/scripts/migrate_webpos_taxes.py').read())
"""

Tax = env['account.tax']
taxes = Tax.search([('active', '=', True)])

ok = []
bad = []
for tax in taxes:
    issues = tax._webpos_configuration_issues()
    if issues:
        bad.append((tax, issues))
    else:
        ok.append(tax)

print('=== OK (%s) — pueden marcarse itx_tax_verified manualmente ===' % len(ok))
for t in ok:
    print(' ', t.display_name, '| amount', t.amount, '| tipo', t.tipo_impuesto_webpos)

print('\n=== MAL CONFIGURADOS (%s) ===' % len(bad))
for t, issues in bad:
    verified = ' [VERIFIED!]' if t.itx_tax_verified else ''
    print(' ', t.display_name, '| amount', t.amount, '| tipo', t.tipo_impuesto_webpos,
          '| group', t.tax_group_id.name, verified)
    for issue in issues:
        print('    -', issue)

if bad:
    to_clear = [t for t, _ in bad if t.itx_tax_verified]
    if to_clear:
        Tax.browse([t.id for t in to_clear]).write({'itx_tax_verified': False})
        print('\nCleared itx_tax_verified on', len(to_clear), 'taxes')
