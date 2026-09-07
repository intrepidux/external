{
    'name': 'L10n DO Fix Report Invoice BMC',
    'summary': 'Bridge BMC: WebPOS + l10n_do_accounting_update (reportes, secuencias, sync)',
    'version': '16.0.1.0.0',
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
        'views/account_move_view_inherit.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
