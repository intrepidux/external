# -*- coding: utf-8 -*-

from odoo import fields,models, api, _
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"

    # Override field to make it editable for WebPOS invoices
    l10n_do_ecf_modification_code = fields.Selection(
        selection="_get_l10n_do_ecf_modification_code",
        string="e-CF Modification Code",
        copy=False,
        readonly=False,  # Changed from True to allow manual selection for WebPOS
    )

    def _get_l10n_do_ecf_modification_code(self):
        """ Return the list of e-CF modification codes required by DGII.
            For WebPOS journals, only codes 1 and 3 are allowed.
        """
        # Check if this invoice is from a WebPOS journal
        if self.journal_id and getattr(self.journal_id, 'is_webpos', False):
            _logger.info("DEBUG: WebPOS journal detected - limiting modification codes to 1 and 3")
            return [
                ("1", _("01 - Cancelación Total")),  # Total Cancellation
                ("3", _("03 - Corrección de Monto")),  # Amount Correction
            ]
        
        # Return all codes for non-WebPOS journals
        return [
            ("1", _("01 - Cancelación Total")),  # Total Cancellation
            ("2", _("02 - Corrección de Texto")),  # Text Correction
            ("3", _("03 - Corrección de Monto")),  # Amount Correction
            ("4", _("04 - Reemplazo de NCF Emitido en Contingencia")),  # NCF Replacement Issued in Contingency
            ("5", _("05 - Referencia a Factura Electrónica de Consumidor Final")),  # Reference Electronic Consumer Invoice
        ]

    
    @api.depends(
        "journal_id",
        "l10n_latam_use_documents",
        "state",
        "l10n_latam_document_type_id",
        "invoice_date", "move_type",
    )

    def _is_manual_document_number(self):

        result = super()._is_manual_document_number()
        
        # Tu parche: notas electrónicas (E33/E34) NO son manuales
        if self.l10n_latam_document_type_id and self.l10n_latam_document_type_id.l10n_do_ncf_type in ("e-credit_note", "e-debit_note"):
            return False

        return result

    def _compute_l10n_do_fiscal_sequence(self):
        super()._compute_l10n_do_fiscal_sequence()
        
        for inv in self:
            if (
                inv.l10n_latam_document_type_id
                and inv.l10n_latam_document_type_id.l10n_do_ncf_type in ("e-credit_note", "e-debit_note")
            ):
                inv.l10n_do_fiscal_sequence_id = inv.env["account.fiscal.sequence"].search(
                    [
                        ("company_id", "parent_of", inv.company_id.ids),
                        ("fiscal_type_id", "=", inv.l10n_latam_document_type_id.id),
                        ("state", "=", "active"),
                    ],
                    order="expiration_date, id desc",
                    limit=1,   
                )     

    def _post(self, soft=True):
        """Override to defer sequence consumption for WebPOS ECF invoices"""
        res = super()._post(soft)

        for inv in self:
            is_webpos_ecf_journal = inv.journal_id and getattr(inv.journal_id, 'is_webpos', False)
            is_ecf_invoice = getattr(inv, 'is_ecf_invoice', False)

            # Solo aplica la lógica de secuencia temporal si es un diario WebPOS ECF
            # y si el número de documento actual no es ya un número temporal de WebPOS.
            if is_webpos_ecf_journal and is_ecf_invoice and not (inv.l10n_latam_document_number or "").startswith("TEMP-"):
                # Si no tiene número o el número actual no es un NCF válido para WebPOS
                if not inv.l10n_latam_document_number or not inv.l10n_latam_document_number[1:3] in (inv.E_CF_VENTAS + inv.E_CF_COMPRAS + inv.E_CF_AJUSTES):
                    temp_number = f"TEMP-{inv.id}"
                    # Restore state logic as in commit 1413838f
                    inv.state = "draft"
                    inv.write({
                        "state": "posted",
                        "l10n_latam_document_number": temp_number,
                        "payment_reference": f'{inv.name} - {temp_number}',
                        "l10n_do_ncf_expiration_date": inv.l10n_do_fiscal_sequence_id.expiration_date if inv.l10n_do_fiscal_sequence_id else False,
                    })
                    _logger.info(f"Deferred sequence consumption (TEMP number assigned) for WebPOS ECF invoice {inv.id}")
            elif not is_webpos_ecf_journal and not inv.l10n_latam_document_number:
                # Lógica para consumo normal si no es una factura WebPOS ECF y no tiene número asignado
                if inv.l10n_do_fiscal_sequence_id:
                    document_number = inv.l10n_do_fiscal_sequence_id.get_fiscal_number()
                    inv.state = "draft"
                    inv.write({
                        "state": "posted",
                        "l10n_latam_document_number": document_number,
                        "l10n_do_ncf_expiration_date": inv.l10n_do_fiscal_sequence_id.expiration_date,
                        "payment_reference": f'{inv.name} - {document_number}',
                    })
                    _logger.info(f"Normal sequence consumption for non-WebPOS ECF invoice {inv.id}")

        return res
