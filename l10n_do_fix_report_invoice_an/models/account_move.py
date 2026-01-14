# -*- coding: utf-8 -*-

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"

    def _post(self, soft=True):
        """Override to defer sequence consumption for WebPOS ECF invoices"""
        res = super()._post(soft)

        for inv in self:
            if (inv.l10n_latam_use_documents and
                not inv.l10n_latam_document_number and
                res and
                inv.l10n_do_fiscal_sequence_id):

                # Check if this is a WebPOS ECF invoice using existing is_ecf_invoice field
                is_webpos_ecf = (
                    getattr(inv, 'is_ecf_invoice', False) and
                    getattr(inv.journal_id, 'is_webpos', False)
                )

                if is_webpos_ecf:
                    # Defer sequence consumption - set temporary number
                    temp_number = f"TEMP-{inv.id}"
                    inv.state = "draft"
                    inv.write({
                        "state": "posted",
                        "l10n_latam_document_number": temp_number,
                        "l10n_do_ncf_expiration_date": inv.l10n_do_fiscal_sequence_id.expiration_date,
                        "payment_reference": f'{inv.name} - {temp_number}',
                    })
                    _logger.info(f"Deferred sequence consumption for WebPOS ECF invoice {inv.id}")
                else:
                    # Normal consumption for non-WebPOS ECF
                    document_number = inv.l10n_do_fiscal_sequence_id.get_fiscal_number()
                    inv.state = "draft"
                    inv.write({
                        "state": "posted",
                        "l10n_latam_document_number": document_number,
                        "l10n_do_ncf_expiration_date": inv.l10n_do_fiscal_sequence_id.expiration_date,
                        "payment_reference": f'{inv.name} - {document_number}',
                    })

        return res
