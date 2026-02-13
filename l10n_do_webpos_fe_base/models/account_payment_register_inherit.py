from odoo import models, fields, api

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    type_payment_id = fields.Many2one(
        comodel_name="tipopago.webpos",
        string="Tipo de pago",
        compute='_compute_type_payment_id',
        store=False,
    )


    @api.depends('journal_id')
    def _compute_type_payment_id(self):
        for wizard in self:
            journal = wizard.journal_id
            if journal and journal.l10n_do_payment_form:
                # Mapeo directo a códigos de WebPOS (independiente de XML IDs)
                # payment_type_map =>
                #     'cash': 'l10n_do_webpos_fe_base.tipo_pago_efectivo',
                #     'bank': 'l10n_do_webpos_fe_base.tipo_pago_cheque',
                #     'card': 'l10n_do_webpos_fe_base.tipo_pago_tdcd',
                #     'credit': 'l10n_do_webpos_fe_base.tipo_pago_vc',
                #     'swap': 'l10n_do_webpos_fe_base.tipo_pago_permuta',
                #     'bond': 'l10n_do_webpos_fe_base.tipo_pago_cr',
                #     'others': 'l10n_do_webpos_fe_base.tipo_pago_ot'
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
                    tipo = self.env['tipopago.webpos'].search([('code_payment_webpos', '=', code)], limit=1)
                    wizard.type_payment_id = tipo.id if tipo else False
                else:
                    wizard.type_payment_id = False
            else:
                wizard.type_payment_id = False