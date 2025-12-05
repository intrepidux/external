# -*- coding: utf-8 -*-
{
    'name': "fix invoice report for Indexa localization Electronic Invoices",

    'summary': """
        fix electronic invoices format
    """,

    'description': """
        Dominican Republic Fiscal electronic invoice format fix
        =====================================================

    """,

    'author': "David Contreras (Garibaldy)",
    'website': "https://www.intrepidux.com",
    'category': 'Accounting/Localizations/Account Charts',
    'version': '17.0.0.0.3',
    'depends': [ 'l10n_do_webpos_fe_base'],
    'data': [
        'views/report_invoice_fix.xml',
    ],
}
