# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class l10n_do_sequence_inherit(models.Model):
    _name = 'l10n.sequence.max'
    _description = 'Control de Secuencias y Alertas para la República Dominicana'

    document_type_id = fields.Many2one("l10n_latam.document.type")
    company_id = fields.Many2one("res.company")
    max = fields.Integer()
    max_alert = fields.Integer()
    user_id = fields.Many2one('res.users')

    def action_send_email(self):
        mail_template = self.env.ref('l10n_do_sequence_inherit.mail_template_sequence_warning')
        mail_template.send_mail(self.id, force_send=True)


class AccountMove(models.Model):
    _inherit = "account.move"

    sequence_current_number = fields.Integer(
        string="Current Sequence Number",
        compute="_compute_sequence_details",
        store=False
    )
    sequence_remaining_count = fields.Integer(
        string="Remaining Sequence Count",
        compute="_compute_sequence_details",
        store=False
    )
    sequence_alert_message = fields.Char(
        string="Sequence Alert Message",
        compute="_compute_sequence_details",
        store=False
    )
    sequence_alert_level = fields.Selection([
        ('none', 'No Alert'),
        ('warning', 'Warning'),
        ('danger', 'Danger')
    ], string="Alert Level", compute="_compute_sequence_details", store=False)

    @api.depends('l10n_do_fiscal_number', 'l10n_latam_document_type_id', 'company_id')
    def _compute_sequence_details(self):
        for record in self:
            if not record.l10n_latam_document_type_id or not record.company_id:
                record.sequence_current_number = 0
                record.sequence_remaining_count = 0
                record.sequence_alert_message = ""
                record.sequence_alert_level = 'none'
                continue

            # Find the sequence configuration for this document type and company
            l10n_max = self.env['l10n.sequence.max'].search([
                ('company_id', '=', record.company_id.id),
                ('document_type_id', '=', record.l10n_latam_document_type_id.id),
            ], limit=1)

            if not l10n_max:
                record.sequence_current_number = 0
                record.sequence_remaining_count = 0
                record.sequence_alert_message = "Estas secuencias no han sido configuradas. Por favor, configure el máximo de comprobantes."
                record.sequence_alert_level = 'warning'
                continue

            # Get current sequence number from fiscal number
            current_number = 0
            if record.l10n_do_fiscal_number and record.l10n_do_fiscal_number.strip():
                try:
                    # Extract number from fiscal number (assuming format like "B0100000001")
                    current_number = int(record.l10n_do_fiscal_number[3:])
                except (ValueError, IndexError):
                    current_number = 0

            record.sequence_current_number = current_number

            # Calculate remaining count
            remaining = l10n_max.max - current_number
            record.sequence_remaining_count = max(0, remaining)

            # Determine alert level and message
            if remaining <= 0:
                record.sequence_alert_level = 'danger'
                record.sequence_alert_message = "¡Las secuencias se han agotado! No se pueden crear más comprobantes de este tipo."
            elif remaining <= l10n_max.max_alert:
                record.sequence_alert_level = 'warning'
                record.sequence_alert_message = f"Quedan {remaining} comprobantes disponibles. Considere renovar las secuencias."
            else:
                record.sequence_alert_level = 'none'
                record.sequence_alert_message = ""

    @api.constrains('l10n_latam_document_type_id', 'company_id', 'l10n_do_fiscal_number')
    def _check_sequence_configuration(self):
        for record in self:
            if record.move_type not in ['in_invoice', 'in_refund'] and record.l10n_latam_document_type_id and record.company_id:
                l10n_max = self.env['l10n.sequence.max'].search([
                    ('company_id', '=', record.company_id.id),
                    ('document_type_id', '=', record.l10n_latam_document_type_id.id),
                ], limit=1)

                if not l10n_max:
                    raise UserError(_("No se puede confirmar la factura. Las secuencias para este tipo de documento no han sido configuradas. Por favor, configure el máximo de comprobantes antes de continuar."))

                # Check if sequences are exhausted
                if record.l10n_do_fiscal_number and record.l10n_do_fiscal_number.strip():
                    try:
                        current_number = int(record.l10n_do_fiscal_number[3:])
                        if current_number >= l10n_max.max:
                            raise UserError(_("No se puede confirmar la factura. El número máximo de comprobantes para este tipo de documento ya ha sido alcanzado. Por favor, renueve las secuencias antes de continuar."))
                    except (ValueError, IndexError):
                        pass  # Invalid fiscal number format, let it pass for now
