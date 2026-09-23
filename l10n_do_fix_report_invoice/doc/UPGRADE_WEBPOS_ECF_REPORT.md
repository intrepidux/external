# Upgrade ritual: WebPOS e-CF invoice document (frozen base)

The WebPOS e-CF PDF uses a **standalone** QWeb root `report_invoice_document_webpos_ecf`, cloned from Odoo core `account.report_invoice_document`. It does **not** inherit `account.report_invoice_document`, so `l10n_do_accounting*` sibling views never merge into this report.

## Translations

The frozen base lives in **this** module, so strings are **not** taken from `account` translations.

- WebPOS e-CF PDF renders with **`t-lang="es_DO"`** (not the partner language), so fiscal/table labels stay in Spanish.
- Table headers are also set in Spanish via `report_invoice_webpos_ecf_do.xml` (no dependency on PO import).
- After deploy, load PO terms once per database:

```bash
odoo-bin -d DB -u l10n_do_fix_report_invoice --load-language=es_DO --stop-after-init
```

Maintain `i18n/es_DO.po` and `i18n/es.po` when re-cloning the base (merge msgids from `account/i18n/es.po`).

## Files

| File | When to edit |
|------|----------------|
| `views/report_invoice_document_webpos_ecf_base.xml` | Only when re-cloning from upstream Odoo |
| `i18n/es_DO.po` | After re-clone or new English labels in base/DO views |
| `views/report_invoice_webpos_ecf_do.xml` | DO fiscal block, table columns, header |
| `views/report_invoice_webpos_ecf.xml` | Totals, QR, payment reference layout |
| `views/report_invoice_webpos_ecf_view_reset.xml` | Migration helper (drops old primary-inherit views on `-u`) |

## Major Odoo upgrade (e.g. 18 → 19)

1. Diff upstream `account/views/report_invoice.xml` (`template id="report_invoice_document"`) against `report_invoice_document_webpos_ecf_base.xml`.
2. Replace the inner body of `report_invoice_document_webpos_ecf` with the new core snapshot. Update the FROZEN comment (version, date).
3. Do **not** put DO/WebPOS logic in the base file.
4. `-u l10n_do_fix_report_invoice` on each database.
5. Fix broken xpaths in `report_invoice_webpos_ecf_do.xml` and `report_invoice_webpos_ecf.xml` if core structure changed.
6. Run verification (below) and print a WebPOS e-CF invoice PDF.

## Verification (Odoo shell)

```python
arch = env.ref('l10n_do_fix_report_invoice.report_invoice_document_webpos_ecf').get_combined_arch()
assert 'webpos_ecf_fiscal_info' in arch
for bad in (
    'l10n_do_accounting_yasmany.fiscal_info',
    'l10n_do_accounting.fiscal_info',
    'is_l10n_do_invoice',
):
    assert bad not in arch

move = env['account.move'].search([
    ('journal_id.is_webpos', '=', True),
    ('state', '=', 'posted'),
    ('move_type', '=', 'out_invoice'),
], limit=20)
move = next(m for m in move if m._get_name_invoice_report() == 'l10n_do_fix_report_invoice.report_invoice_document_webpos_ecf')
report = env.ref('account.account_invoices')
html = report._render_qweb_html(report.report_name, move.ids)[0].decode()
assert 'l10n_do_accounting_yasmany.fiscal_info' not in html
```

## Migrating from primary + isolate (≤ 1.0.25)

Module `18.0.1.0.26+` loads `report_invoice_webpos_ecf_view_reset.xml` before the base to remove the old `primary="True"` view on `account.report_invoice_document`. One `-u` is enough.
