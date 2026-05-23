{
    'name': 'L10n Do Fix Report Invoice, yasmany',
    'author': "Intrepidux SRL, David Contreras",
    'website': "http://www.intrepidux.com",
    "license": "OPL-1",
    "support": "soporte@intrepidux.com",
    'category': 'Localization',
    'version': "18.0.1.0.4",
    'depends': ['l10n_do_webpos_fe_base', ],
    'data': [
        # 'security/ir.model.access.csv', 
        'views/report_invoice_fix.xml',
        'wizard/account_move_reversal_inherit_views.xml',
        'views/account_journal_views.xml',
    ],
}
