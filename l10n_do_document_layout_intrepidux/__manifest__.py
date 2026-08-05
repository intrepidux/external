{
    "name": "Rep. Dom. — Document Layout Intrepidux",
    "version": "17.0.1.0.7",
    "category": "Localization",
    "summary": "Factura fiscal DO en marco Intrepidux (meta en article + QR footer)",
    "author": "Intrepidux",
    "license": "LGPL-3",
    "depends": [
        "itx_document_layout",
        "itx_document_layout_account",
        "l10n_do_accounting",
        "l10n_do_dgii_fix_report_invoice_vbs",
    ],
    "data": [
        "report/header_do_fiscal.xml",
        "report/footer_ecf_slot.xml",
        "report/report_invoice_do_intrepidux.xml",
    ],
    "assets": {
        "web.report_assets_common": [
            "l10n_do_document_layout_intrepidux/static/src/scss/l10n_do_intrepidux.scss",
        ],
    },
    "installable": True,
    "auto_install": True,
}
