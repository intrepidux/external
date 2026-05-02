from odoo import models, fields, api

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    type_payment_id = fields.Many2one(
        comodel_name="tipopago.dgii",
        string="Tipo de pago",
        compute='_compute_type_payment_id',
        store=False,
    )


    @api.depends('journal_id')
    def _compute_type_payment_id(self):
        for wizard in self:
            journal = wizard.journal_id
            if journal and journal.l10n_do_payment_form:
                # Mapeo a códigos estándar DGII para tipos de pago
                payment_type_map = {
                    'cash': '01',
                    'bank': '02',
                    'card': '03',
                    'credit': '04',
                    'bond': '05',
                    'swap': '06',
                    'others': '08'
                }
                code = payment_type_map.get(journal.l10n_do_payment_form)
                if code:
                    # Búsqueda segura por código técnico
                    tipo = self.env['tipopago.dgii'].search([('code_payment_dgii', '=', code)], limit=1)
                    wizard.type_payment_id = tipo.id if tipo else False
                else:
                    wizard.type_payment_id = False
            else:
                wizard.type_payment_id = False