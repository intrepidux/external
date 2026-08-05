# l10n_do_document_layout_intrepidux

Puente **República Dominicana** + layout **Intrepidux** (`itx_document_layout`).

## Qué hace

- Con `external_report_layout_id` = Intrepidux y factura fiscal DO (`is_l10n_do_invoice`):
  - **Badge:** tipo documento + NCF/e-NCF (no el `name` genérico de account glue).
  - **Header:** panel `invoice_do_meta_panel` vía `itx_header_meta_l10n` (cliente + emisor + NCF).
  - **Oculta** `#issuer_info` y bloque partner duplicado en el body.
  - **QR e-CF** (`itx_dgii_electronic_stamp`) en `itx_footer_qr_slot` (misma URL que VBS).
  - QR en body desactivado cuando Intrepidux está activo.

## Qué no hace

- No redefine ITBIS, columnas e-CF, firmas Recibido/Autorizado (siguen en `l10n_do_accounting` / VBS).
- No modifica POS ni `external_layout` core.

## Depends

`itx_document_layout`, `itx_document_layout_account`, `l10n_do_accounting`, `l10n_do_dgii_fix_report_invoice_vbs` — **auto_install**.

## Smoke

1. Empresa DO, layout Intrepidux, factura posted con e-CF.
2. PDF: meta fiscal en header, QR en footer, contenido fiscal del body igual que con Light.
