# -*- coding: utf-8 -*-

from odoo import models


class L10nLatamDocumentType(models.Model):
    _inherit = "l10n_latam.document.type"

    def _get_l10n_do_ncf_types(self):
        selection = super()._get_l10n_do_ncf_types()
        ecf_selection = [
            ("e-fiscal", "31"),
            ("e-consumer", "32"),
            ("e-debit_note", "33"),
            ("e-credit_note", "34"),
            ("e-informal", "41"),
            ("e-minor", "43"),
            ("e-special", "44"),
            ("e-governmental", "45"),
            ("e-export", "46"),
            ("e-exterior", "47"),
        ]
        existing_keys = {key for key, label in selection}
        return selection + [
            item for item in ecf_selection if item[0] not in existing_keys
        ]

