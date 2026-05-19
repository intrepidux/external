# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    # Override field to make it editable for dgii ecf invoices
    l10n_do_ecf_modification_code = fields.Selection(
        selection="_get_l10n_do_ecf_modification_code",
        string="e-CF Modification Code",
        copy=False,
        readonly=False,
    )

    def _get_l10n_do_ecf_modification_code(self):
        """ Return the list of e-CF modification codes required by DGII.
            For DGII ECF journals, only codes 1 and 3 are allowed.
        """
        if self.journal_id and getattr(self.journal_id, 'is_dgii', False):
            _logger.info("DEBUG: DGII journal detected - limiting modification codes to 1 and 3")
            return [
                ("1", _("01 - Cancelación Total")),
                ("3", _("03 - Corrección de Monto")),
            ]

        return [
            ("1", _("01 - Cancelación Total")),
            ("2", _("02 - Corrección de Texto")),
            ("3", _("03 - Corrección de Monto")),
            ("4", _("04 - Reemplazo de NCF Emitido en Contingencia")),
            ("5", _("05 - Referencia a Factura Electrónica de Consumidor Final")),
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
        """Posponer consumo de secuencia fiscal en facturas e-CF con diario DGII hasta el flujo XML."""
        res = super()._post(soft)

        for inv in self:
            is_dgii_ecf_journal = inv.journal_id and getattr(inv.journal_id, 'is_dgii', False)
            is_ecf_invoice = getattr(inv, 'is_ecf_invoice', False)

            # Secuencia temporal solo si es diario DGII ECF y el número no es ya TEMP-.
            if is_dgii_ecf_journal and is_ecf_invoice and not (inv.l10n_latam_document_number or "").startswith("TEMP-"):
                if not inv.l10n_latam_document_number or not inv.l10n_latam_document_number[1:3] in (
                    inv.E_CF_VENTAS + inv.E_CF_COMPRAS + inv.E_CF_AJUSTES
                ):
                    temp_number = f"TEMP-{inv.id}"
                    inv.state = "draft"
                    inv.write({
                        "state": "posted",
                        "l10n_latam_document_number": temp_number,
                        "payment_reference": f'{inv.name} - {temp_number}',
                        "l10n_do_ncf_expiration_date": inv.l10n_do_fiscal_sequence_id.expiration_date if inv.l10n_do_fiscal_sequence_id else False,
                    })
                    _logger.info(
                        "Deferred sequence consumption (TEMP number assigned) for DGII ECF invoice %s",
                        inv.id,
                    )
            elif not is_dgii_ecf_journal and not inv.l10n_latam_document_number:
                if inv.l10n_do_fiscal_sequence_id:
                    document_number = inv.l10n_do_fiscal_sequence_id.get_fiscal_number()
                    inv.state = "draft"
                    inv.write({
                        "state": "posted",
                        "l10n_latam_document_number": document_number,
                        "l10n_do_ncf_expiration_date": inv.l10n_do_fiscal_sequence_id.expiration_date,
                        "payment_reference": f'{inv.name} - {document_number}',
                    })
                    _logger.info(
                        "Normal sequence consumption for non-DGII ECF invoice %s",
                        inv.id,
                    )

        return res

    def _l10n_do_dgii_fix_consume_fiscal_if_needed_for_xml(self):
        for invoice in self:
            if invoice.state != 'posted':
                continue
            if not invoice.is_invoice(include_receipts=False):
                continue
            if invoice.company_id.country_id.code != 'DO':
                continue
            if not getattr(invoice.journal_id, 'is_dgii', False):
                continue
            if not getattr(invoice, 'is_ecf_invoice', False):
                continue
            if not invoice.journal_id.l10n_latam_use_documents:
                continue
            if invoice._defer_dgii_test_xsd_sequence() and not self.env.context.get(
                'l10n_do_dgii_allow_fiscal_consume'
            ):
                continue
            num = (invoice.l10n_latam_document_number or '').strip()
            if num and not num.startswith('TEMP-'):
                continue
            invoice._compute_l10n_do_fiscal_sequence()
            seq = invoice.l10n_do_fiscal_sequence_id
            if not seq:
                _logger.warning(
                    "DGII FE fix: factura %s sin secuencia fiscal activa para tipo %s.",
                    invoice.name,
                    invoice.l10n_latam_document_type_id.display_name
                    if invoice.l10n_latam_document_type_id
                    else '?',
                )
                continue
            document_number = seq.get_fiscal_number()
            invoice.write({'state': 'draft'})
            invoice.write({
                'state': 'posted',
                'l10n_latam_document_number': document_number,
                'l10n_do_ncf_expiration_date': seq.expiration_date,
                'payment_reference': '%s - %s' % (invoice.name, document_number),
            })
            _logger.info(
                "DGII FE fix: e-NCF asignado antes del XML para %s: %s",
                invoice.name,
                document_number,
            )
