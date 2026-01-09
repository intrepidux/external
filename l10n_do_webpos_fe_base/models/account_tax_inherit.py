from odoo import api, fields, models, _

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

    itx_tax_verified = fields.Boolean(string='Verificado para WebPOS', default=False)
    itx_tax_included = fields.Boolean(string='Precio incluye impuesto (WebPOS)', default=False, help='Indica si este impuesto genera precios inclusive en las líneas de productos')
