{
    'name': 'L10n Do dgii fix report invoice VBS',
    'version': '1.5',
    'depends': [
        'account',
        'l10n_do_accounting',
        'l10n_do_dgii_fe_base',
        'web',
    ],
    'data': [
        'data/l10n_do_ecf_document_types.xml',
        'views/res_company_views.xml',
        'views/report_invoice_fix.xml',
        'views/account_move_view_inherit.xml',
        # 'wizard/account_move_reversal_inherit_views.xml',

    ],
    'post_init_hook': 'post_init_hook',
}
