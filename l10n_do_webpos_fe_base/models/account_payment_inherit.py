
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class account_payment(models.Model):
    _inherit = 'account.payment'
    _description = 'Herencia de pagos para agregar tipo de pago'

    type_payment_id = fields.Many2one(
        comodel_name="tipopago.webpos",
        string="Tipo de pago",
        required=False,
        compute='_compute_type_payment_id',
        #default=lambda self: self.env.ref('l10n_do_webpos_fe_base.tipo_pago_efectivo').id
    )


    @api.depends('journal_id')
    def _compute_type_payment_id(self):

            journal_id = self["journal_id"].id
            journal = self.env['account.journal'].browse(journal_id)
            self.type_payment_id = self._get_payment_type_id(journal) if self._get_payment_type_id(journal) else self.env.ref('l10n_do_webpos_fe_base.tipo_pago_efectivo').id


           

    def _get_payment_type_id(self, journal):
        """Devuelve el ID del tipo de pago basado en el Diario (journal)."""
        payment_type_map = {
            'cash': 'l10n_do_webpos_fe_base.tipo_pago_efectivo',
            'bank': 'l10n_do_webpos_fe_base.tipo_pago_cheque',
            'card': 'l10n_do_webpos_fe_base.tipo_pago_tdcd',
            'credit': 'l10n_do_webpos_fe_base.tipo_pago_cr',
            'swap': 'l10n_do_webpos_fe_base.tipo_pago_permuta',
            'bond': 'l10n_do_webpos_fe_base.tipo_pago_vc',
            'others': 'l10n_do_webpos_fe_base.tipo_pago_ot'
        }
        
        tipo_pago = payment_type_map.get(journal.l10n_do_payment_form)
        return self.env.ref(tipo_pago).id if tipo_pago else None


    @api.model
    def update_payment_defaults(self):
        payments = self.search([])
        _logger.info("XXXXXXXXXXXXXXACTUALIZAR %s ACTUALIZARXXXXXXXXXXXXXXXX",payments)
        for payment in payments:
            journal_id = payment.journal_id.id
            if journal_id:
                journal = self.env['account.journal'].browse(journal_id)
                payment_type_id = self._get_payment_type_id(journal)
                if payment_type_id:
                    payment.type_payment_id = payment_type_id


