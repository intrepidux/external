# -*- coding: utf-8 -*-
from odoo import api, models, fields


class Municipality(models.Model):
    _name = 'res.municipality'
    _description = 'Municipality'
    _order = 'ecf_code'

    name = fields.Char('Name', required=True)
    ecf_code = fields.Char(
        'Code', help='Código DGII del municipio (6 dígitos)', required=True
    )
    country_id = fields.Many2one('res.country', string='Country', required=True)
    state_id = fields.Many2one(
        'res.country.state', 'State', domain="[('country_id', '=', country_id)]"
    )

    _sql_constraints = [
        (
            'name_code_uniq',
            'unique(state_id, ecf_code)',
            'El código del municipio debe ser único por provincia.',
        )
    ]

    @api.model
    def _name_search(self, search_value, args=None, operator='ilike', limit=100, order=None):
        args = args or []
        domain = args + [
            '|',
            ('name', operator, search_value),
            ('ecf_code', operator, search_value),
        ]
        return self._search(domain, limit=limit, order=order)
