# BMC WebPOS — Auditoría (2026-03-05)

## Stack WebPOS (alcance)

```
l10n_do → l10n_do_webpos_fe_base → l10n_do_fix_report_invoice_bmc → l10n_do_accounting_update
```

## Rol del bridge (`l10n_do_fix_report_invoice_bmc`)

Parches mínimos de colisión entre `webpos_fe_base` y el stack del cliente:

| Pieza | Qué hace |
|-------|----------|
| `_get_webpos_fiscal_document_number` | NCF vía `l10n_latam_sequence_id` (accounting_update) |
| `_bmc_should_skip_webpos_send` | No re-enviar facturas con `sync_id` (sync_objects_vbs) |
| `_is_manual_document_number` | e-CF en diario WebPOS no exige NCF manual |
| `_check_l10n_latam_documents` | Permite tipos e-* sin número manual |
| `MyXmlData.verify_sent_encf` | Copia `qr_code` → `l10n_do_electronic_stamp` para el PDF |
| `report_invoice_fix.xml` | CSS tabla PDF |
| `account_move_view_inherit.xml` | Visibilidad `dgi_status` / `l10n_do_ecf_sign_date` |

Impuestos WebPOS (`tipo_impuesto_webpos`, validación `itx_tax_verified`) viven en **`l10n_do_webpos_fe_base`**.

## Dependencias entre módulos WebPOS

| Módulo | Depende de |
|--------|------------|
| `l10n_do_webpos_fe_base` | `base`, `account`, `l10n_do` |
| `l10n_do_fix_report_invoice_bmc` | `l10n_do_webpos_fe_base`, `l10n_do_accounting_update`, `l10n_do_accounting` |

## Diarios WebPOS (`is_webpos`)

- Campo en `account.journal` (core `l10n_do_webpos_fe_base`).
- BMC: WebPOS en **compras**; ventas vía `sync_objects_vbs` (sin cruce operativo).

## Orden de instalación / actualización

1. `l10n_do_accounting_update`
2. `l10n_do_webpos_fe_base`
3. `l10n_do_fix_report_invoice_bmc`

```bash
odoo-bin -d <db> -u l10n_do_webpos_fe_base,l10n_do_fix_report_invoice_bmc --stop-after-init
```

## Tipos e-CF (E31–E47)

Cargados por `l10n_do_accounting` (`data/l10n_latam.document.type.csv`, XML IDs `ecf_*`).
**No** duplicar en el bridge.

## Impuestos

- Configuración y constraint en `l10n_do_webpos_fe_base`.
- Auditoría manual: `scripts/migrate_webpos_taxes.py` (solo reporta).
