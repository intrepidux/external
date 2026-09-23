{
    'name': 'L10n Do Fix Report Invoice, Yasmany',
    'author': "Intrepidux SRL, David Contreras",
    'website': "http://www.intrepidux.com",
    "license": "OPL-1",
    "support": "soporte@intrepidux.com",
    'category': 'Localization',
    'version': "18.0.1.0.29",
    'depends': [
        'web',
        'account',
        'l10n_do_webpos_fe_base',
    ],
    'data': [
        'views/report_invoice_webpos_ecf_view_reset.xml',
        'views/report_invoice_document_webpos_ecf_base.xml',
        'views/report_invoice_webpos_ecf_do.xml',
        'views/report_invoice_webpos_ecf.xml',
        'views/report_invoice_routing.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'l10n_do_fix_report_invoice/static/src/scss/report_invoice_webpos_ecf.scss',
        ],
    },
}
