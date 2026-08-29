{
    'name': "ITX WebPOS FE Base - República Dominicana",
    'summary': """
        Integración facturación electrónica WebPOS compatible con cualquier localización dominicana
        """,
    'author': "Intrepidux SRL, David Contreras",
    'website': "http://www.intrepidux.com",
    "license": "OPL-1",
    "support": "soporte@intrepidux.com",
    'category': 'Localization',
    'version': "18.0.1.0.1",

    # any module necessary for this one to work correctly
    'depends': ['base','account','l10n_do'],

    # always loaded
   'data': [
        'data/account_webpos_data.xml',
        'data/ir_cron_webpos_followup.xml',
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
        
    ],
    # "post_init_hook": "post_init_hook", //revisar maximo recursions en actualizacion odoo sh

}
