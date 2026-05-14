# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    res_municipality_id = fields.Many2one(
        'res.municipality',
        string='Municipality',
        domain="[('state_id', '=', state_id)]",
    )

    @api.onchange('res_municipality_id')
    def _onchange_res_municipality_id(self):
        if self.res_municipality_id:
            self.city = self.res_municipality_id.name
