from odoo import models, fields

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    is_webpos = fields.Boolean(string="¿Es WebPOS?", default=False) 