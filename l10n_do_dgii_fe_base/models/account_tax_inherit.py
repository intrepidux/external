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
        help=(
            'Categoría DGII en Odoo (códigos 0–6). No coincide numéricamente con '
            'IndicadorFacturacion del XML (0–4). En retenciones (tasa %% negativa) puede marcarse '
            'el código de la naturaleza subyacente del ítem (p. ej. gravado ⇒ 1). '
            'Tabla: README «Equivalencias DGII».'
        ),
        # Sin default. Si el impuesto está «Verificado para DGII», un grupo **ITBIS** exige
        # valor; en grupos no-ITBIS (ISR, etc.) puede quedar vacío.
        # Nota: 0–3, 5, 6 son categorías ITBIS en e-CF → conviene grupo de impuesto ITBIS.
        # El 4 (no facturable hoteles/rest.) es la excepción típica sin grupo ITBIS en el nombre.
    )

    itx_tax_verified = fields.Boolean(string='Verificado para DGII', default=False)

    dgii_codigo_tabla_impuesto = fields.Char(
        string='Código TablaImpuestoAdicional (001–039)',
        size=3,
        help=(
            'Código XSD de impuesto adicional (p. ej. 006 ISC, 001 propina si no usa grupo «Propina»). '
            'Distinto de tipo_impuesto_dgii (0–6, categoría ITBIS en Odoo).'
        ),
    )

    @api.constrains('dgii_codigo_tabla_impuesto')
    def _check_dgii_codigo_tabla_impuesto(self):
        for tax in self:
            cod = (tax.dgii_codigo_tabla_impuesto or '').strip()
            if not cod:
                continue
            if len(cod) == 3 and cod.isdigit():
                ni = int(cod)
                if 1 <= ni <= 39:
                    continue
            raise ValidationError(
                _('Código TablaImpuestoAdicional debe ser 001–039 (tres dígitos).')
            )

    @api.constrains('itx_tax_verified', 'tipo_impuesto_dgii', 'tax_group_id')
    def _check_dgii_verified_requires_tipo(self):
        """ISR/retenciones u otros grupos no-ITBIS pueden estar verificados sin ``tipo_impuesto_dgii``."""
        for tax in self:
            if not tax.itx_tax_verified or tax.tipo_impuesto_dgii:
                continue
            gname_u = (
                ((tax.tax_group_id.name or '') if tax.tax_group_id else '').upper()
            )
            if 'ITBIS' in gname_u:
                raise ValidationError(
                    _('Un impuesto del grupo ITBIS marcado como verificado para DGII debe tener '
                      'Tipo de Impuesto DGII seleccionado (%s).')
                    % (tax.display_name,)
                )

    @api.constrains(
        'tipo_impuesto_dgii', 'tax_group_id', 'amount', 'itx_tax_verified', 'amount_type'
    )
    def _check_dgii_tipo_itbis_group(self):
        """Tipos ITBIS en e-CF deben ir con grupo cuyo nombre indique ITBIS; el 4 es la excepción.

        Retenciones (porcentaje del maestro negativo: ``amount`` < 0) pueden cargar código 0–3, 5–6
        sobre grupo ISR/etc. para clasificar ``IndicadorFacturacion`` en líneas sólo-retención.

        Solo aplica cuando el maestro está «Verificado para DGII». Impuestos con
        ``amount_type == group`` (agrupación) pueden usar otro nombre de grupo: la coherencia
        ITBIS se valida en los hijos; además permite destildar la verificación sin bloqueos.
        """
        itbis_tipos = {'0', '1', '2', '3', '5', '6'}
        for tax in self:
            if not tax.itx_tax_verified:
                continue
            if tax.amount_type == 'group':
                continue
            tipo = tax.tipo_impuesto_dgii
            if not tipo or tipo not in itbis_tipos:
                continue
            gname = (tax.tax_group_id.name or '') if tax.tax_group_id else ''
            if 'ITBIS' in gname.upper():
                continue
            # Retenciones: el maestro usa ``amount`` negativo; permite tipo ITBIS DGII en grupo ISR.
            if (tax.amount or 0.0) < 0:
                continue
            raise ValidationError(
                _('Para el tipo de impuesto DGII seleccionado en %(tax)s, el grupo de impuesto '
                  'debe contener «ITBIS» en el nombre (categorías ITBIS en e-CF). '
                  'La opción «No facturable (Hoteles y/o Restaurantes)» (4) es la que admite '
                  'otros grupos cuando no aplica ITBIS.')
                % {'tax': tax.display_name}
            )
