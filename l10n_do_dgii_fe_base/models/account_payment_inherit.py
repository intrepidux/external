from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class account_payment(models.Model):
    _inherit = 'account.payment'
    _description = 'Herencia de pagos para agregar tipo de pago'

    type_payment_id = fields.Many2one(
        comodel_name="tipopago.dgii",
        string="Tipo de pago",
        required=False,
        compute='_compute_type_payment_id',
        # store=True  # Se recomienda dejarlo sin store si causa problemas en la instalación
    )

    @api.depends('journal_id')
    def _compute_type_payment_id(self):
        for rec in self:
            journal = rec.journal_id
            payment_type_id = rec._get_payment_type_id(journal)
            if payment_type_id:
                rec.type_payment_id = payment_type_id
            else:
                # Fallback seguro: busca el código '01' (Efectivo) en lugar de usar env.ref
                efectivo = self.env['tipopago.dgii'].search([('code_payment_dgii', '=', '01')], limit=1)
                rec.type_payment_id = efectivo.id if efectivo else False

    def _get_payment_type_id(self, journal):
        """Devuelve el ID del tipo de pago basado en el Diario (journal)."""

        if not journal or not journal.l10n_do_payment_form:
            return False

        # Mapeo ajustado a códigos técnicos de DGII(01-08)
        payment_code_map = {
            'cash': '01',
            'bank': '02',
            'card': '03',
            'credit': '04',
            'bond': '05',
            'swap': '06',
            'others': '08'
        }
        
        code = payment_code_map.get(journal.l10n_do_payment_form)
        if code:
            # Búsqueda por código en lugar de env.ref para evitar errores de caché/instalación
            tipo = self.env['tipopago.dgii'].search([('code_payment_dgii', '=', code)], limit=1)
            return tipo.id if tipo else False
        return False

    @api.model
    def update_payment_defaults(self):
        payments = self.search([('type_payment_id', '=', False)])
        _logger.info("XXXXXXXXXXXXXX ACTUALIZANDO %s PAGOS SIN TIPO XXXXXXXXXXXXXX", len(payments))
        for payment in payments:
            payment_type_id = self._get_payment_type_id(payment.journal_id)
            if payment_type_id:
                payment.type_payment_id = payment_type_id