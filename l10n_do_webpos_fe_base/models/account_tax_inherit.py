from odoo import api, fields, models

class account_journal(models.Model):
    _inherit = 'account.tax'
    _description = 'Herencia paara agregar informacion de impuesto para webpos'

    tipo_impuesto_webpos = fields.Selection([
    ('0', 'Exento'),
    ('1', '18% (ITBIS 1)'),
    ('2', '16% (ITBIS 2)'),
    ('3', '0% ITBIS (Aplica para E46)'),
    ('4', 'No facturable Hoteles y/o Restaurantes'),
    ('5', '18% + 10% (ITBIS 1 + 10% Ley)'),
    ('6', 'Exento + 10% (Exento + 10% de Ley)'),
   
    ], string='Tipo de Impuesto webpos', default='0', required=True)