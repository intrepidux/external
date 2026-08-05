from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_pos_order(self):
        result = super()._loader_params_pos_order()
        result['search_params']['fields'].extend([
            'itx_dgii_electronic_stamp',
            'l10n_do_ecf_security_code',
            'l10n_do_ecf_sign_date',
        ])
        return result
