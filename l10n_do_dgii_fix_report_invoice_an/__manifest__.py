{
    'name': 'L10n Do dgii fix report invoice AN',
    'version': '15.0.1.0.2',
    'depends': [
         'l10n_do_dgii_fe_base', 'web', 'l10n_do_accounting'
    ],
    'data': [
        'views/report_invoice_fix.xml',
        'views/account_move_view_inherit.xml',
        # 'wizard/account_move_reversal_inherit_views.xml',

    ],
}