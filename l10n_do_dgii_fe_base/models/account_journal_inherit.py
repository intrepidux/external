from odoo import models, fields, api

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    is_dgii = fields.Boolean(string="¿Es DGII?", default=False)
