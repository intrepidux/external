# BMC WebPOS — Auditoría (2026-03-05)

## Stack WebPOS (alcance)

```
l10n_do → l10n_do_webpos_fe_base → l10n_do_fix_report_invoice_bmc → l10n_do_accounting_update
```

## Dependencias entre módulos WebPOS

| Módulo | Depende de |
|--------|------------|
| `l10n_do_webpos_fe_base` | `base`, `account`, `l10n_do` |
| `l10n_do_fix_report_invoice_bmc` | `l10n_do_webpos_fe_base`, `l10n_do_accounting_update`, `l10n_do_accounting` |

Ningún otro módulo de FE paralelo forma parte de este stack.

## Diarios WebPOS (`is_webpos`)

- Campo en `account.journal` (core `l10n_do_webpos_fe_base`).
- BMC: WebPOS en **compras**; ventas vía `sync_objects_vbs` (sin cruce operativo).
- Verificar en BD del cliente:

```sql
SELECT j.id, j.name, j.type, j.is_webpos
FROM account_journal j
WHERE j.is_webpos = true;
```

## Orden de instalación / actualización

1. `l10n_do_accounting_update` (ya instalado en BMC)
2. `l10n_do_webpos_fe_base`
3. `l10n_do_fix_report_invoice_bmc`

```bash
odoo-bin -d <db> -u l10n_do_webpos_fe_base,l10n_do_fix_report_invoice_bmc --stop-after-init
```

## Tipos e-CF (E31–E47)

Cargados por `l10n_do_fix_report_invoice_bmc/data/l10n_latam.document.type.csv` (XML IDs `ecf_*` del propio bridge, no de terceros).

## Impuestos

- `tipo_impuesto_webpos` + `itx_tax_verified` deben configurarse **manualmente**.
- Auditoría: `scripts/migrate_webpos_taxes.py` (solo reporta, no auto-verifica).
