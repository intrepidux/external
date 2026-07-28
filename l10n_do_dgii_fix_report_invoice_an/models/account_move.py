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
        'l10n_latam_document_type_id',
        'journal_id',
        'move_type',
        'reversed_entry_id',
        'reversed_entry_id.l10n_latam_manual_document_number',
    )
    def _compute_l10n_latam_manual_document_number(self):
        recs_with_journal = self.filtered(
            lambda x: x.journal_id and x.journal_id.l10n_latam_use_documents
        )
        for rec in recs_with_journal:
            rec.l10n_latam_manual_document_number = rec._is_manual_document_number(
                rec.journal_id
            )
        (self - recs_with_journal).l10n_latam_manual_document_number = False

    def _is_manual_document_number(self, journal):
        if not self:
            return super()._is_manual_document_number(journal)
        self.ensure_one()

        if (
            self.l10n_latam_document_type_id
            and self.l10n_latam_document_type_id.l10n_do_ncf_type
            in ("e-credit_note", "e-debit_note")
        ):
            return False

        if (
            self.reversed_entry_id
            and self.reversed_entry_id.l10n_latam_document_type_id.l10n_do_ncf_type
            in ("e-informal", "e-minor", "e-exterior")
        ):
            return False

        if self.reversed_entry_id:
            return self.reversed_entry_id.l10n_latam_manual_document_number

        do_country = self.env.ref("base.do", raise_if_not_found=False)
        if (
            do_country
            and self.company_id.country_id == do_country
            and self.l10n_latam_document_type_id
        ):
            return self.move_type in (
                "in_invoice",
                "in_refund",
            ) and self.l10n_latam_document_type_id.l10n_do_ncf_type not in (
                "minor",
                "e-minor",
                "informal",
                "e-informal",
                "exterior",
                "e-exterior",
            )

        return super()._is_manual_document_number(journal)

    def _dgii_fix_ecf_type_prefixes(self):
        return (
            getattr(self, "E_CF_VENTAS", [])
            + getattr(self, "E_CF_COMPRAS", [])
            + getattr(self, "E_CF_AJUSTES", [])
        )

    def _dgii_fix_needs_temp_document_number(self):
        """True si el e-CF DGII debe llevar TEMP-{id} antes de consumir secuencia real."""
        self.ensure_one()
        if not (self.journal_id and getattr(self.journal_id, "is_dgii", False)):
            return False
        if not getattr(self, "is_ecf_invoice", False):
            return False
        num = (self.l10n_latam_document_number or "").strip()
        if num.startswith("TEMP-"):
            return False
        if num and len(num) >= 3 and num[1:3] in self._dgii_fix_ecf_type_prefixes():
            return False
        return True

    def _dgii_fix_assign_temp_document_number(self):
        self.ensure_one()
        self._compute_l10n_do_fiscal_sequence()
        temp_number = "TEMP-%s" % self.id
        vals = {
            "l10n_latam_document_number": temp_number,
            "payment_reference": "%s - %s" % (self.name, temp_number)
            if self.name and self.name != "/"
            else temp_number,
        }
        if self.l10n_do_fiscal_sequence_id:
            vals["l10n_do_ncf_expiration_date"] = (
                self.l10n_do_fiscal_sequence_id.expiration_date
            )
        self.write(vals)
        _logger.info(
            "Deferred sequence consumption (TEMP number assigned) for DGII ECF invoice %s",
            self.id,
        )

    def _defer_dgii_test_xsd_sequence(self):
        self.ensure_one()
        cre = self.company_id.fe_dgii_id.filtered(lambda p: p.active)[:1]
        return bool(
            cre
            and cre.dgii_client_mode == "test"
            and cre.dgii_validate_xsd
        )

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
        for inv in self:
            if inv._dgii_fix_needs_temp_document_number():
                inv._dgii_fix_assign_temp_document_number()

        res = super()._post(soft)

        for inv in self:
            is_dgii_ecf_journal = inv.journal_id and getattr(
                inv.journal_id, "is_dgii", False
            )
            is_ecf_invoice = getattr(inv, "is_ecf_invoice", False)

            if is_dgii_ecf_journal and is_ecf_invoice:
                num = (inv.l10n_latam_document_number or "").strip()
                if num.startswith("TEMP-") and inv.name and inv.name != "/":
                    inv.write({
                        "payment_reference": "%s - %s" % (inv.name, num),
                    })
                continue

            if not is_dgii_ecf_journal and not inv.l10n_latam_document_number:
                if inv.l10n_do_fiscal_sequence_id:
                    document_number = inv.l10n_do_fiscal_sequence_id.get_fiscal_number()
                    inv.state = "draft"
                    inv.write({
                        "state": "posted",
                        "l10n_latam_document_number": document_number,
                        "l10n_do_ncf_expiration_date": inv.l10n_do_fiscal_sequence_id.expiration_date,
                        "payment_reference": "%s - %s" % (inv.name, document_number),
                    })
                    _logger.info(
                        "Normal sequence consumption for non-DGII ECF invoice %s",
                        inv.id,
                    )

        return res

    def build_xml_to_print(self, invoice, type_document):
        invoice._l10n_do_dgii_fix_consume_fiscal_if_needed_for_xml()
        return super().build_xml_to_print(invoice, type_document)

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
            if invoice.itx_xml_data_id:
                invoice.itx_xml_data_id.name = document_number
            _logger.info(
                "DGII FE fix: e-NCF asignado antes del XML para %s: %s",
                invoice.name,
                document_number,
            )
