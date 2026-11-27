# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EcfDraftBypassWizard(models.TransientModel):
    _name = 'ecf.draft.bypass.wizard'
    _description = 'Confirmación omitir bloqueo e-CF'

    move_id = fields.Many2one(
        'account.move',
        string='Comprobante',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    action = fields.Selection(
        selection=[
            ('draft', 'Restablecer a borrador'),
            ('cancel', 'Cancelar asiento'),
        ],
        string='Acción',
        required=True,
        default='draft',
    )
    reason = fields.Text(
        string='Motivo',
        required=True,
        help='Queda registrado en el historial del comprobante.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move = self.env['account.move'].browse(
            self.env.context.get('active_id')
        ).exists()
        if move:
            res.setdefault('move_id', move.id)
            if not move._ecf_dgii_is_locked_for_draft():
                raise UserError(_(
                    'Este comprobante no tiene bloqueo e-CF; use el flujo normal.'
                ))
        return res

    def _check_user_may_bypass(self):
        if not self.env.user.has_group(
            'l10n_do_dgii_fe_base.group_ecf_draft_bypass'
        ):
            raise UserError(_(
                'No tiene permiso para omitir el bloqueo de borrador e-CF.'
            ))

    def action_confirm(self):
        self.ensure_one()
        self._check_user_may_bypass()
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_('Indique el motivo.'))
        ctx = {
            'ecf_draft_bypass': True,
            'ecf_draft_bypass_reason': reason,
        }
        move = self.move_id.with_context(**ctx)
        if self.action == 'draft':
            move.button_draft()
        else:
            move.button_cancel()
        return {'type': 'ir.actions.act_window_close'}