from odoo import api, fields, models

class tipo_pago_dgii(models.Model):
    _name = 'tipopago.dgii'
    _description = 'Maestro para definir tipos de pago para los diarios'
    _rec_name = 'name_payment_dgii'

    code_payment_dgii = fields.Char(string="Codigo pago dgii",size=2,required=True)
    name_payment_dgii = fields.Char(string="Nombre tipo pago dgii", required=True)          
    payment_id = fields.One2many('account.payment', 'type_payment_id', string='Pago')    
        