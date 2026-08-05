{
    'name': "POS DGII Electronic Invoicing",
    'summary': "Capa FE delgada entre l10n_do_pos y l10n_do_dgii_fe_base.",
    'author': "Iterativo SRL",
    'license': 'LGPL-3',
    'category': 'Localization',
    'version': '17.0.1.0.0',
    'depends': [
        'l10n_do_pos',
        'l10n_do_dgii_fe_base',
        'l10n_do_dgii_fix_report_invoice_vbs',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'l10n_do_pos_dgii_fe/static/src/**/*',
        ],
    },
    'installable': True,
}
