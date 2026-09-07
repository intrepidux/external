# Deploy / upgrade WebPOS BMC

## Pre-requisitos

1. Backup de base de datos
2. `l10n_do_accounting_update` instalado
3. Parámetro `webpos_api.base_url` configurado

## Docker (doo16)

```bash
cd doo16
docker compose stop odoo
docker compose run --rm odoo odoo -d doo16 --stop-after-init \
  -u l10n_do_webpos_fe_base,l10n_do_fix_report_invoice_bmc
docker compose start odoo
```

Primera instalación (si no están en `ir_module_module`):

```bash
docker compose run --rm odoo odoo -d doo16 --stop-after-init \
  -i l10n_do_webpos_fe_base,l10n_do_fix_report_invoice_bmc
```

## Post-deploy (manual)

1. **Credenciales** — Compañía → FE Webpos → ambiente activo (apk, url, licencia)
2. **Diario compras** — marcar `¿Es WebPOS?`
3. **Impuestos** — mapear `tipo_impuesto_webpos` y marcar `Verificado para WebPOS` solo si cuadra
4. **Auditoría impuestos** (shell):

```python
exec(open('custom/bmc/kvillar93/bmcargo_vbs/l10n_do_fix_report_invoice_bmc/scripts/migrate_webpos_taxes.py').read())
```

## XMLs pendientes (opcional, solo si hay historial)

```python
recs = env['my.xml.data'].search([
    ('status', 'in', ['pending', 'error']),
    ('account_move_id.state', '=', 'posted'),
])
for rec in recs:
    rec.rebuild_xml_to_send()
```

## Verificación

- Cron `WebPOS FE - Follow-up send/verify` activo (10 min)
- Factura compra e-CF en diario WebPOS: `my.xml.data` pending → sent → procesed
- PDF con QR / código seguridad (campos en `l10n_do_accounting_update`)

Ver también: [QA_CHECKLIST.md](QA_CHECKLIST.md)
