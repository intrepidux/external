# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def _l10n_do_ecf_document_type(self, ncf_type):
        return self.env["l10n_latam.document.type"].search([
            ("country_id.code", "=", "DO"),
            ("code", "=", "E"),
            ("l10n_do_ncf_type", "=", ncf_type),
        ], limit=1)

    def _reverse_move_vals(self, default_values, cancel=True):
        res = super()._reverse_move_vals(default_values=default_values, cancel=cancel)
        if self.l10n_latam_country_code == "DO" and self.is_ecf_invoice and self.move_type == "out_invoice":
            document_type = self._l10n_do_ecf_document_type("e-credit_note")
            if document_type:
                res["l10n_latam_document_type_id"] = document_type.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("is_ecf_invoice") or not vals.get("journal_id") or not vals.get("move_type"):
                continue

            journal = self.env["account.journal"].browse(vals["journal_id"])
            if not journal.l10n_latam_use_documents:
                continue

            document_type = False
            if vals["move_type"] in ("out_refund", "in_refund"):
                document_type = self.env.ref(
                    "l10n_do_dgii_fix_report_invoice_vbs.ecf_credit_note_client",
                    raise_if_not_found=False,
                )
            elif vals.get("is_debit_note") and vals["move_type"] in ("out_invoice", "in_invoice"):
                document_type = self.env.ref(
                    "l10n_do_dgii_fix_report_invoice_vbs.ecf_debit_note_client",
                    raise_if_not_found=False,
                )

            if document_type:
                vals["l10n_latam_document_type_id"] = document_type.id

        return super().create(vals_list)
