from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    fe_webpos_id = fields.One2many('itx.fe.webpos', 'company_id', string="Web POS Credentials")