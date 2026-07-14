# -*- coding: utf-8 -*-

from odoo import api, models, _
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    def _is_manual_document_number(self):
        """Override: retorna False para ECF (usa _is_l10n_do_dgii_allowed_document de l10n_do_dgii_fe_base).

        El módulo l10n_do_dgii_fe_base ya tiene el mapping exacto de tipos E-CF
        (E_CF_VENTAS, E_CF_COMPRAS, E_CF_AJUSTES) y el método
        _is_l10n_do_dgii_allowed_document() para validar documentos ECF por flujo.
        """
        if self._is_l10n_do_dgii_allowed_document():
            return False
        return super()._is_manual_document_number()

    def _check_l10n_latam_documents(self):
        """Override to include electronic NCF types (e-informal, e-minor, etc.) 
        in the validation, since base l10n_do_accounting only allows 
        ['minor', 'informal', 'exterior', False] but mode 'e' uses e-* variants.
        """
        validated_invoices = self.filtered(
            lambda x: x.l10n_latam_use_documents and x.state == "posted"
        )
        without_doc_type = validated_invoices.filtered(
            lambda x: not x.l10n_latam_document_type_id
        )
        if without_doc_type:
            raise ValidationError(
                _(
                    "The journal require a document type but not document type "
                    "has been selected on invoices %s.",
                    without_doc_type.ids,
                )
            )

        without_number = validated_invoices.filtered(
            lambda x: not x.l10n_latam_document_number
            and x.l10n_latam_manual_document_number
        )

        # Allow all e-* electronic NCF types in addition to base types
        allowed_types = [
            "minor",
            "informal",
            "exterior",
            False,
            "e-minor",
            "e-informal",
            "e-exterior",
            "e-fiscal",
            "e-consumer",
            "e-special",
            "e-governmental",
            "e-export",
            "e-debit_note",
            "e-credit_note",
        ]

        if validated_invoices.l10n_ncf_type_name:
            if (
                without_number
                and self.l10n_ncf_type_name in ["minor", "e-minor"]
                and self.journal_id.l10n_latam_use_documents
                and self.partner_id.vat != self.env.company.vat
            ):
                raise ValidationError(
                    _(
                        "Minor expenses VAT must be the same as the company "
                        "reporting them."
                    )
                )

        if validated_invoices.l10n_ncf_type_name not in allowed_types:
            raise ValidationError(
                _(
                    "Please set the document number on the following invoices %s.",
                    without_number.ids,
                )
            )

        return super(AccountMove, self)._check_l10n_latam_documents()