from odoo import api, fields, models, _

class account_journal(models.Model):
    _inherit = 'account.tax'
    _description = 'Herencia paara agregar informacion de impuesto para webpos'

    tipo_impuesto_webpos = fields.Selection([
    ('0', 'Exento'),
    ('1', '18% (ITBIS 1)'),
    ('2', '16% (ITBIS 2)'),
    ('3', '0% ITBIS (Aplica para E46)'),
    ('4', 'No facturable Hoteles y/o Restaurantes'),
    ('5', '18% + 10% (ITBIS 1 + 10% Ley)'),
    ('6', 'Exento + 10% (Exento + 10% de Ley)'),

    ], string='Tipo de Impuesto webpos', default='0', required=True)

    itx_tax_verified = fields.Boolean(string='Verificado para WebPOS', default=False)
    itx_tax_included = fields.Boolean(string='Precio incluye impuesto (WebPOS)', default=False, help='Indica si este impuesto genera precios inclusive en las líneas de productos')

    @api.constrains('tax_group_id')
    def _check_single_tax_per_group(self):
        """Ensure only one tax per tax_group_id is applied to invoice lines for WebPOS."""
        for tax in self:
            if tax.tax_group_id:
                # Find other taxes in the same group
                duplicate_taxes = self.search([
                    ('tax_group_id', '=', tax.tax_group_id.id),
                    ('id', '!=', tax.id),
                    ('company_id', '=', tax.company_id.id)
                ])
                if duplicate_taxes:
                    raise models.ValidationError(
                        _("No puede haber más de un impuesto del mismo grupo '%s' "
                          "por línea en facturas WebPOS. Impuestos duplicados: %s") % (
                            tax.tax_group_id.name,
                            ', '.join(duplicate_taxes.mapped('name'))
                        )
                    )
