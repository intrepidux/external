{
    'name': 'L10n DO Fix Report Invoice BMC',
    'summary': 'Bridge BMC: parches de colisión WebPOS + accounting_update (reporte/vistas)',
    'version': '16.0.1.0.10',
    'category': 'Localization',
    'license': 'LGPL-3',
    'depends': [
        'web',
        'account',
        'l10n_do',
        'l10n_do_accounting',
        'l10n_do_accounting_update',
        'l10n_do_webpos_fe_base',
    ],
    'data': [
        'data/l10n_latam.document.type.csv',
        'views/report_invoice_fix.xml',
        'views/account_journal_views.xml',
        'wizard/account_move_reversal_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
