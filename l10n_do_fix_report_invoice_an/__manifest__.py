{
    'name': 'L10n Do Fix Report Invoice, AN',
    'version': '1.1',
    'depends': ['l10n_do_accounting','l10n_do_webpos_fe_base'],
    'data': [
        'views/report_invoice_fix.xml',
        'views/account_move_view_inherit.xml',
        # 'wizard/account_move_reversal_inherit_views.xml',

    ],
}
