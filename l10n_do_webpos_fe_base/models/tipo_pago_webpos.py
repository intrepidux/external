from odoo import api, fields, models

class tipo_pago_webpos(models.Model):
    _name = 'tipopago.webpos'
    _description = 'Maestro para definir tipos de pago para los diarios'
    _rec_name = 'name_payment_webpos'

    code_payment_webpos = fields.Char(string="Codigo pago webpos",size=2,required=True)
    name_payment_webpos = fields.Char(string="Nombre tipo pago webpos", required=True)          
    payment_id = fields.One2many('account.payment', 'type_payment_id', string='Pago')    
        