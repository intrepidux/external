import time
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    itx_dgii_electronic_stamp = fields.Char(
        related='account_move.itx_dgii_electronic_stamp',
        readonly=True,
    )
    l10n_do_ecf_security_code = fields.Char(
        related='account_move.l10n_do_ecf_security_code',
        readonly=True,
    )
    l10n_do_ecf_sign_date = fields.Datetime(
        related='account_move.l10n_do_ecf_sign_date',
        readonly=True,
    )
    itx_dgii_status = fields.Selection(
        related='account_move.itx_dgii_status',
        readonly=True,
    )
    itx_dgii_dgi_err_msg = fields.Char(
        related='account_move.itx_dgii_dgi_err_msg',
        readonly=True,
    )

    def _export_for_ui(self, order):
        result = super()._export_for_ui(order)
        result.update({
            'itx_dgii_electronic_stamp': order.itx_dgii_electronic_stamp or '',
            'l10n_do_ecf_security_code': order.l10n_do_ecf_security_code or '',
            'l10n_do_ecf_sign_date': order.l10n_do_ecf_sign_date or '',
        })
        return result

    @api.model
    def get_ecf_data_from_invoice(self, order_server_ids):
        if not order_server_ids:
            return False

        orders = self.search([('id', 'in', order_server_ids)])
        for _attempt in range(3):
            for order in orders:
                if not order.account_move:
                    continue
                invoice = order.account_move
                stamp = invoice.itx_dgii_electronic_stamp
                if stamp:
                    return {
                        'itx_dgii_electronic_stamp': stamp,
                        'l10n_do_ecf_security_code': invoice.l10n_do_ecf_security_code or '',
                        'l10n_do_ecf_sign_date': (
                            invoice.l10n_do_ecf_sign_date.isoformat()
                            if invoice.l10n_do_ecf_sign_date else ''
                        ),
                        'itx_dgii_status': invoice.itx_dgii_status or '',
                    }
            time.sleep(1)
            orders.invalidate_recordset([
                'account_move',
                'itx_dgii_electronic_stamp',
                'l10n_do_ecf_security_code',
                'l10n_do_ecf_sign_date',
            ])
        return False
