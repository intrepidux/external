# -*- coding: utf-8 -*-

from odoo import models, fields

class AccountJournal(models.Model):
    _inherit = "account.journal"

    l10n_do_is_shared_sequence_source = fields.Boolean(
        string="Fuente de Secuencias Compartidas",
        help="Marque si este diario es la fuente de secuencias compartidas para otros diarios. (nota credito/debito)"
    )