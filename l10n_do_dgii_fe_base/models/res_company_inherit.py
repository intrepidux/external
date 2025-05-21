from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    fe_dgii_id = fields.One2many('itx.fe.dgii', 'company_id', string="DGII Credentials")
