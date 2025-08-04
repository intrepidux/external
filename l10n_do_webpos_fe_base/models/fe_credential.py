from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class IntrepiduxFacturacionElectronica(models.Model):
    _name = 'itx.fe.webpos'
    _description = 'Maestro de facturacion electronica'

    name = fields.Char(string='Ambiente', required=True)
    companyLicCod = fields.Char(string='companyLicCod', required=True)
    branchCod = fields.Char(string='branch Code', required=True)
    posCod = fields.Char(string='POS CODE', required=True)
    apk = fields.Char(string='apk code', required=True)
    url_base = fields.Char(string='url', required=True)
    # xml_data_ids = fields.One2many('my.xml.data', 'fiscal_printer_id', string='XML creation Logs')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    active = fields.Boolean(string='Activo', default=False)

    @api.constrains('company_id', 'active')
    def _check_unique_active_per_company(self):
        for record in self:
            if record.active:
                existing_active = self.search_count([
                    ('company_id', '=', record.company_id.id),
                    ('active', '=', True),
                    #('id', '!=', record.id)  # Excluir el registro actual
                ])
                if existing_active > 1:
                    raise ValidationError("Solo puede haber un registro activo por compañía.")