from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountTax(models.Model):
    _inherit = 'account.tax'

    tipo_impuesto_dgii = fields.Selection(
        [
            ('0', 'Exento'),
            ('1', '18% (ITBIS 1)'),
            ('2', '16% (ITBIS 2)'),
            ('3', '0% ITBIS (Aplica para E46)'),
            ('4', 'No facturable Hoteles y/o Restaurantes'),
            ('5', '18% + 10% (ITBIS 1 + 10% Ley)'),
            ('6', 'Exento + 10% (Exento + 10% de Ley)'),
        ],
        string='Tipo de Impuesto DGII',
        # Sin default: configuración explícita cuando el impuesto se use en DGII.
    )

    itx_tax_verified = fields.Boolean(string='Verificado para DGII', default=False)

    @api.constrains('itx_tax_verified', 'tipo_impuesto_dgii')
    def _check_dgii_verified_requires_tipo(self):
        for tax in self:
            if tax.itx_tax_verified and not tax.tipo_impuesto_dgii:
                raise ValidationError(
                    _('Un impuesto marcado como verificado para DGII debe tener '
                      'Tipo de Impuesto DGII seleccionado (%s).')
                    % (tax.display_name,)
                )
