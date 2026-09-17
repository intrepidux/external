# -*- coding: utf-8 -*-

from odoo import _, api, fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    bmc_has_e_credit_note_sequence = fields.Boolean(
        compute='_compute_bmc_has_e_credit_note_sequence',
        string='Has E34 credit note sequence',
    )

    @api.depends(
        'l10n_do_sequence_ids',
        'l10n_do_sequence_ids.l10n_latam_document_type_id',
        'l10n_latam_use_documents',
        'type',
        'company_id.country_id',
    )
    def _compute_bmc_has_e_credit_note_sequence(self):
        e34 = self._bmc_get_e_credit_note_document_type()
        for journal in self:
            if not e34 or not journal._bmc_is_purchase_fiscal_journal():
                journal.bmc_has_e_credit_note_sequence = False
                continue
            journal.bmc_has_e_credit_note_sequence = bool(
                journal.l10n_do_sequence_ids.filtered(
                    lambda seq: seq.l10n_latam_document_type_id == e34
                )
            )

    def _get_journal_ncf_types(self, counterpart_partner=False, invoice=False):
        """Purchase WebPOS journals must expose E34 (e-credit_note) sequences."""
        res = super()._get_journal_ncf_types(
            counterpart_partner=counterpart_partner,
            invoice=invoice,
        )
        self.ensure_one()
        if (
            self.type != 'purchase'
            or not self.l10n_latam_use_documents
        ):
            return res

        if self.company_id.country_id.code != 'DO':
            return res

        extras = ['credit_note', 'e-credit_note']
        if invoice and invoice.move_type in ('in_refund', 'out_refund'):
            merged = list(extras)
            if res:
                merged.extend(res if isinstance(res, list) else [res])
            return list(dict.fromkeys(merged))

        if not counterpart_partner and not invoice:
            res_list = list(res or [])
            for extra in extras:
                if extra not in res_list:
                    res_list.append(extra)
            return res_list

        return res

    @api.model
    def _bmc_get_e_credit_note_document_type(self):
        doc_type = self.env.ref(
            'l10n_do_fix_report_invoice_bmc.ecf_credit_note_client',
            raise_if_not_found=False,
        )
        if doc_type:
            return doc_type
        return self.env['l10n_latam.document.type'].search(
            [
                ('country_id.code', '=', 'DO'),
                ('l10n_do_ncf_type', '=', 'e-credit_note'),
            ],
            limit=1,
        )

    def _bmc_is_purchase_fiscal_journal(self):
        self.ensure_one()
        country = self.company_id.country_id
        return (
            self.type == 'purchase'
            and self.l10n_latam_use_documents
            and country
            and country.code == 'DO'
        )

    def _bmc_ensure_webpos_credit_note_sequence(self):
        """Create missing E34 fiscal sequence on purchase fiscal journals."""
        e34 = self._bmc_get_e_credit_note_document_type()
        if not e34:
            return self.env['ir.sequence']

        Sequence = self.env['ir.sequence'].sudo()
        created = Sequence
        for journal in self:
            if not journal._bmc_is_purchase_fiscal_journal():
                continue
            if journal.l10n_do_sequence_ids.filtered(
                lambda seq: seq.l10n_latam_document_type_id == e34
            ):
                continue
            created |= Sequence.create(
                e34._get_document_sequence_vals_2(journal)
            )
        return created

    def action_bmc_ensure_webpos_credit_note_sequence(self):
        self._bmc_ensure_webpos_credit_note_sequence()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Secuencia NC electrónica'),
                'message': _(
                    'Se verificó la secuencia E34 (Nota de Crédito Electrónica) '
                    'en el diario. Actualice la página si no la ve aún.'
                ),
                'type': 'success',
                'sticky': False,
            },
        }
