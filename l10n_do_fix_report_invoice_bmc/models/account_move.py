# -*- coding: utf-8 -*-

from odoo import api, models, _
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_webpos_fiscal_document_number(self):
        """BMC: assign e-NCF via l10n_latam_sequence_id (accounting_update)."""
        self.ensure_one()
        if self.l10n_latam_sequence_id:
            return self.l10n_latam_sequence_id.next_by_id()
        return super()._get_webpos_fiscal_document_number()

    def _bmc_should_skip_webpos_send(self):
        """Skip WebPOS when invoice comes from sync or already has fiscal number."""
        self.ensure_one()
        if hasattr(self, 'sync_id') and self.sync_id:
            return True
        if getattr(self, 'l10n_do_fiscal_number', False):
            return True
        return False

    def _is_webpos_candidate_for_post(self):
        self.ensure_one()
        if not super()._is_webpos_candidate_for_post():
            return False
        return not self._bmc_should_skip_webpos_send()

    def _webpos_send_and_verify(self, raise_on_error=False):
        if self._bmc_should_skip_webpos_send():
            return False
        return super()._webpos_send_and_verify(raise_on_error=raise_on_error)

    def _is_manual_document_number(self):
        if hasattr(self, '_is_l10n_do_webpos_allowed_document'):
            if self.journal_id.is_webpos and self._webpos_is_ecf_invoice():
                return False
        return super()._is_manual_document_number()

    def _check_l10n_latam_documents(self):
        validated_invoices = self.filtered(
            lambda x: x.l10n_latam_use_documents and x.state == 'posted'
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

        allowed_types = [
            'minor', 'informal', 'exterior', False,
            'e-minor', 'e-informal', 'e-exterior', 'e-fiscal', 'e-consumer',
            'e-special', 'e-governmental', 'e-export', 'e-debit_note', 'e-credit_note',
        ]

        if validated_invoices.l10n_ncf_type_name:
            if (
                without_number
                and self.l10n_ncf_type_name in ['minor', 'e-minor']
                and self.journal_id.l10n_latam_use_documents
                and self.partner_id.vat != self.env.company.vat
            ):
                raise ValidationError(
                    _(
                        'Minor expenses VAT must be the same as the company '
                        'reporting them.'
                    )
                )

        if validated_invoices.l10n_ncf_type_name not in allowed_types:
            raise ValidationError(
                _(
                    'Please set the document number on the following invoices %s.',
                    without_number.ids,
                )
            )

        return super(AccountMove, self)._check_l10n_latam_documents()

    @api.model_create_multi
    def create(self, vals_list):
        if not isinstance(vals_list, list):
            vals_list = [vals_list]

        ecf_credit = self.env.ref(
            'l10n_do_fix_report_invoice_bmc.ecf_credit_note_client',
            raise_if_not_found=False,
        )
        ecf_debit = self.env.ref(
            'l10n_do_fix_report_invoice_bmc.ecf_debit_note_client',
            raise_if_not_found=False,
        )

        for vals in vals_list:
            if not vals.get('is_ecf_invoice'):
                continue
            journal = self.env['account.journal'].browse(vals.get('journal_id'))
            if not journal.l10n_latam_use_documents:
                continue
            move_type = vals.get('move_type')
            if move_type in ('out_refund', 'in_refund') and ecf_credit:
                vals['l10n_latam_document_type_id'] = ecf_credit.id
            if vals.get('is_debit_note') and move_type in ('out_invoice', 'in_invoice') and ecf_debit:
                vals['l10n_latam_document_type_id'] = ecf_debit.id

        return super().create(vals_list)
