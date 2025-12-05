{
    'name': "ITX L10n DO Webpos FE Base",
    'summary': """
        Integracion facturacion electronica webpos República Dominicana
        """,
    'author': "Intrepidux SRL, David Contreras",
    'website': "http://www.intrepidux.com",
    "license": "OPL-1",
    "support": "soporte@intrepidux.com",
    'category': 'Localization',
    'version': "17.0.1.0.24",

    # any module necessary for this one to work correctly
    'depends': ['base','account','account_debit_note','l10n_do_accounting'],

    # always loaded
   'data': [
        'security/ir.model.access.csv',
        'views/account_journal_inherit.xml',
        'views/account_move_inherit.xml',
        'views/account_payment_inherit.xml',
        'views/account_tax_inherit.xml',
        'views/fe_credentials.xml',
        'views/fe_webpos_navigation.xml',
        'views/res_company_inherit.xml',
        'views/tipo_pago_webpos.xml', 
        'views/xml_data_logs_menu.xml',
        'data/account_webpos_data.xml',
    ],
    # "post_init_hook": "post_init_hook", //revisar maximo recursions en actualizacion odoo sh

}
