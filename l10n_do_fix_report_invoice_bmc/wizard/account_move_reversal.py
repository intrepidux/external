# -*- coding: utf-8 -*-

from odoo import api, fields, models


class AccountMoveReversal(models.TransientModel):
    _inherit = 'account.move.reversal'

    bmc_is_webpos_reversal = fields.Boolean(
        compute='_compute_bmc_is_webpos_reversal',
        string='WebPOS e-CF Reversal',
    )
    bmc_nc_warning_over_30 = fields.Boolean(
        compute='_compute_bmc_nc_warning',
        string='NC over 30 days',
    )
    bmc_nc_days_diff = fields.Integer(
        compute='_compute_bmc_nc_warning',
        string='Days since original invoice',
    )
    bmc_nc_original_invoice = fields.Char(
        compute='_compute_bmc_nc_warning',
        string='Original invoice',
    )
    bmc_nc_original_date = fields.Date(
        compute='_compute_bmc_nc_warning',
        string='Original invoice date',
    )

    @api.model
    def _bmc_move_is_webpos_ecf_reversal(self, move):
        if not move or move.move_type not in ('in_invoice', 'out_invoice'):
            return False
        journal = move.journal_id
        if not journal.is_webpos or not journal.l10n_latam_use_documents:
            return False
        Move = self.env['account.move']
        prefix = Move._bmc_ecf_prefix_from_ncf(move._bmc_webpos_fiscal_number())
        return Move._bmc_is_webpos_ecf_prefix(prefix)

    @api.depends('move_ids', 'move_ids.journal_id.is_webpos')
    def _compute_bmc_is_webpos_reversal(self):
        for wizard in self:
            move = wizard.move_ids[:1]
            wizard.bmc_is_webpos_reversal = wizard._bmc_move_is_webpos_ecf_reversal(
                move
            )

    @api.depends('move_ids', 'date', 'bmc_is_webpos_reversal')
    def _compute_bmc_nc_warning(self):
        for wizard in self:
            wizard.bmc_nc_warning_over_30 = False
            wizard.bmc_nc_days_diff = 0
            wizard.bmc_nc_original_invoice = False
            wizard.bmc_nc_original_date = False
            if not wizard.bmc_is_webpos_reversal:
                continue
            move = wizard.move_ids[:1]
            if not move or not wizard.date:
                continue
            wizard.bmc_nc_original_invoice = move.display_name
            wizard.bmc_nc_original_date = move.invoice_date or move.date
            wizard.bmc_nc_days_diff = self.env['account.move']._bmc_nc_days_since_origin(
                move, wizard.date
            )
            wizard.bmc_nc_warning_over_30 = wizard.bmc_nc_days_diff > 30

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []
        if active_model != 'account.move' or len(active_ids) != 1:
            return res

        move = self.env['account.move'].browse(active_ids[0])
        if not self._bmc_move_is_webpos_ecf_reversal(move):
            return res

        res.update({
            'journal_id': move.journal_id.id,
            'refund_type': 'full_refund',
            'refund_method': 'refund',
            'l10n_do_ecf_modification_code': '1',
        })
        if 'l10n_do_refund_type' in self._fields:
            res['l10n_do_refund_type'] = 'full_refund'
        if 'is_ecf_invoice' in self._fields:
            res['is_ecf_invoice'] = True
        return res

    @api.depends('move_ids')
    def _compute_document_type(self):
        super()._compute_document_type()
        Move = self.env['account.move']
        for record in self:
            move = record.move_ids[:1]
            if not move or not move.journal_id.is_webpos:
                continue
            if move.move_type not in ('in_invoice', 'out_invoice'):
                continue
            if not Move._bmc_is_webpos_ecf_prefix(
                Move._bmc_ecf_prefix_from_ncf(move._bmc_webpos_fiscal_number())
            ):
                continue
            doc_type = Move._bmc_get_e_credit_note_document_type()
            if doc_type:
                record.l10n_latam_document_type_id = doc_type

    def _prepare_default_reversal(self, move):
        res = super()._prepare_default_reversal(move)
        if not self._bmc_move_is_webpos_ecf_reversal(move):
            return res

        Move = self.env['account.move']
        doc_type = Move._bmc_get_e_credit_note_document_type()
        if doc_type:
            res['l10n_latam_document_type_id'] = doc_type.id

        origin_ncf = move.l10n_latam_document_number or move.l10n_do_fiscal_number
        if origin_ncf:
            res['l10n_do_origin_ncf'] = origin_ncf

        res['l10n_do_ecf_modification_code'] = '1'
        return res

    def reverse_moves(self):
        self.ensure_one()
        if self.bmc_is_webpos_reversal:
            action = super(
                AccountMoveReversal,
                self.with_context(
                    l10n_do_ecf_modification_code='1',
                    refund_type='full_refund',
                ),
            ).reverse_moves()
        else:
            action = super().reverse_moves()

        if (
            self.bmc_is_webpos_reversal
            and self.bmc_nc_warning_over_30
            and self.new_move_ids
        ):
            self.new_move_ids._bmc_apply_nc_over_30_exempt_taxes(
                nc_date=self.date
            )
        return action
