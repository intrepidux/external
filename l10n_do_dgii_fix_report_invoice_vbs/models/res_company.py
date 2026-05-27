# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_do_ecf_issuer = fields.Boolean(
        string="Is e-CF issuer",
        help="Enable electronic fiscal document sequences for this company.",
    )
    l10n_do_fiscal_sequence_mode = fields.Selection(
        selection=[
            ("b", "Serie B"),
            ("e", "Serie E"),
            ("both", "Series B y E"),
        ],
        default="b",
        required=True,
        string="Fiscal Sequence Series",
        help="Controls whether Dominican fiscal journals use paper NCF, electronic e-CF, or both document series.",
    )

    @api.onchange("l10n_do_fiscal_sequence_mode")
    def _onchange_l10n_do_fiscal_sequence_mode(self):
        for company in self:
            if company.l10n_do_fiscal_sequence_mode in ("e", "both"):
                company.l10n_do_ecf_issuer = True

    @api.onchange("l10n_do_ecf_issuer")
    def _onchange_l10n_do_ecf_issuer(self):
        for company in self:
            if not company.l10n_do_ecf_issuer and company.l10n_do_fiscal_sequence_mode in ("e", "both"):
                company.l10n_do_fiscal_sequence_mode = "b"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_l10n_do_fiscal_sequence_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        sequence_mode_changed = bool(
            {"l10n_do_fiscal_sequence_mode", "l10n_do_ecf_issuer"} & set(vals)
        )
        self._normalize_l10n_do_fiscal_sequence_vals(vals)

        res = super().write(vals)
        if sequence_mode_changed:
            for company in self:
                self.env["account.journal"].generate_missing_fiscal_sequences_for_company(company)
        return res

    @api.model
    def _normalize_l10n_do_fiscal_sequence_vals(self, vals):
        if vals.get("l10n_do_ecf_issuer") is False:
            vals["l10n_do_fiscal_sequence_mode"] = "b"
        elif vals.get("l10n_do_fiscal_sequence_mode") in ("e", "both"):
            vals["l10n_do_ecf_issuer"] = True
        return vals

    def init(self):
        """Keep companies that were already e-CF issuers on electronic sequences."""
        self.env.cr.execute(
            """
            UPDATE res_company
               SET l10n_do_fiscal_sequence_mode = 'e'
             WHERE l10n_do_ecf_issuer IS TRUE
               AND COALESCE(l10n_do_fiscal_sequence_mode, 'b') = 'b'
            """
        )
