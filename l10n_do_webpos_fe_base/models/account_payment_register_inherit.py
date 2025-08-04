from odoo import models, fields, api

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    type_payment_id = fields.Many2one(
        comodel_name="tipopago.webpos",
        string="Tipo de pago",
        compute='_compute_type_payment_id',
        store=True,
    )

    @api.depends('journal_id')
    def _compute_type_payment_id(self):
        for wizard in self:
            journal = wizard.journal_id
            if journal:
                payment_type_map = {
                    'cash': 'l10n_do_webpos_fe_base.tipo_pago_efectivo',
                    'bank': 'l10n_do_webpos_fe_base.tipo_pago_cheque',
                    'card': 'l10n_do_webpos_fe_base.tipo_pago_tdcd',
                    'credit': 'l10n_do_webpos_fe_base.tipo_pago_vc',
                    'swap': 'l10n_do_webpos_fe_base.tipo_pago_permuta',
                    'bond': 'l10n_do_webpos_fe_base.tipo_pago_cr',
                    'others': 'l10n_do_webpos_fe_base.tipo_pago_ot'
                }
                tipo_pago = payment_type_map.get(journal.l10n_do_payment_form)
                wizard.type_payment_id = self.env.ref(tipo_pago).id if tipo_pago else False
            else:
                wizard.type_payment_id = False 