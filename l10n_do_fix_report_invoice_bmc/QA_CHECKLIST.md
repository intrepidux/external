# QA Checklist — WebPOS BMC v16

## Instalación

- [ ] `-u l10n_do_webpos_fe_base,l10n_do_fix_report_invoice_bmc` sin errores
- [ ] Cron `WebPOS FE - Follow-up send/verify` activo (cada 10 min)
- [ ] Parámetro `webpos_api.base_url` configurado

## Compras WebPOS

- [ ] Diario compra con `is_webpos=True` y credenciales `itx.fe.webpos` activas
- [ ] Factura e-CF tipo E41/E43/E47 confirma
- [ ] Impuesto sin `itx_tax_verified` bloquea confirmación
- [ ] `my.xml.data` pasa pending → sent → procesed
- [ ] `l10n_do_ecf_security_code` y `l10n_do_ecf_sign_date` se llenan tras verify

## Exclusiones

- [ ] Factura con `sync_id` no envía a WebPOS
- [ ] Factura ventas en diario no-WebPOS sin cambios

## Reporte

- [ ] PDF factura: tabla con columnas alineadas
- [ ] QR visible cuando `l10n_do_electronic_stamp` está poblado

## Regresión

- [ ] Secuencias híbridas B+E en journals (`l10n_do_accounting_update`)
- [ ] NC/ND e-CF usan tipos de `l10n_do_fix_report_invoice_bmc`
