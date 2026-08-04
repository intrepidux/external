{
    'name': "ITX DGII FE Base - República Dominicana",
    'summary': "Integración facturación electrónica DGII compatible con cualquier localización dominicana",
    'description': "Módulo base para la integración de Facturación Electrónica (ECF) con los servicios de DGII a través de una API externa.",
    'author': "Intrepidux SRL, David Contreras",
    'website': "http://www.intrepidux.com",
    'license': "OPL-1",
    'support': "soporte@intrepidux.com",
    'category': 'Localization',
    'version': "15.0.0.3",
    'installable': True,
    'application': False,
    'auto_install': False,


    # any module necessary for this one to work correctly
    'depends': ['base', 'contacts', 'account', 'l10n_do'],

    # always loaded
   'data': [
        'data/account_dgii_data.xml',
        'data/res_country_state_data.xml',
        'data/res.municipality.csv',
        'security/ir.model.access.csv',
        'wizard/dgii_xml_preview_wizard_views.xml',
        'views/account_journal_inherit.xml',
        'views/account_move_inherit.xml',
        'views/account_payment_inherit.xml',
        'views/account_tax_inherit.xml',
        'views/fe_credentials.xml',
        'views/fe_dgii_navigation.xml',
        'views/res_company_inherit.xml',
        'views/res_partner_inherit.xml',
        'views/tipo_pago_dgii.xml', 
        'views/xml_data_logs_menu.xml',
        
    ],
    # "post_init_hook": "post_init_hook",

}