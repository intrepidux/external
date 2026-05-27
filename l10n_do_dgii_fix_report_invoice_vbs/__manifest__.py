{
    'name': 'L10n Do dgii fix report invoice AN',
    'version': '1.3',
    'depends': [
        'l10n_do_accounting_vbs',
        'l10n_do_dgii_fe_base',
    ],
    'data': [
        'data/l10n_do_ecf_document_types.xml',
        'views/res_company_views.xml',
        'views/report_invoice_fix.xml',
        'views/account_move_view_inherit.xml',
        # 'wizard/account_move_reversal_inherit_views.xml',

    ],
}
