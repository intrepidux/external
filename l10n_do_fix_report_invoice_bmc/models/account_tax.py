# -*- coding: utf-8 -*-

from odoo import api, models, _
from odoo.exceptions import ValidationError


class AccountTax(models.Model):
    _inherit = 'account.tax'

    ITBIS_TIPOS = {'0', '1', '2', '3', '5', '6'}

    def _webpos_tax_group_name(self):
        self.ensure_one()
        return ((self.tax_group_id.name or '') if self.tax_group_id else '').upper()

    def _webpos_is_itbis_group(self):
        return 'ITBIS' in self._webpos_tax_group_name()

    def _webpos_is_withholding(self):
        self.ensure_one()
        return (self.amount or 0.0) < 0.0

    def _webpos_configuration_issues(self):
        """Human-readable reasons why this tax must not be marked verified yet."""
        self.ensure_one()
        issues = []
        gname = self._webpos_tax_group_name()
        tipo = self.tipo_impuesto_webpos
        amount = self.amount or 0.0

        if self.amount_type == 'group':
            issues.append(_('es un grupo de impuestos (configurar en los hijos)'))
            return issues

        if self._webpos_is_itbis_group() and not self._webpos_is_withholding():
            if amount == 0.0 and tipo not in ('0', '3'):
                issues.append(
                    _('ITBIS 0%% debe usar tipo WebPOS 0 (Exento) o 3 (0%% ITBIS E46), no %(tipo)s')
                    % {'tipo': tipo}
                )
            elif abs(amount - 18.0) < 0.01 and tipo != '1':
                issues.append(
                    _('ITBIS 18%% debe usar tipo WebPOS 1, no %(tipo)s (%(name)s)')
                    % {'tipo': tipo, 'name': dict(self._fields['tipo_impuesto_webpos'].selection).get(tipo)}
                )
            elif abs(amount - 16.0) < 0.01 and tipo != '2':
                issues.append(
                    _('ITBIS 16%% debe usar tipo WebPOS 2, no %(tipo)s')
                    % {'tipo': tipo}
                )
            elif abs(amount - 1.8) < 0.01 and tipo != '5':
                issues.append(
                    _('ITBIS 1.8%% (10%% ley) debe usar tipo WebPOS 5, no %(tipo)s')
                    % {'tipo': tipo}
                )
            elif amount not in (0.0,) and abs(amount - 18.0) >= 0.01 and abs(amount - 16.0) >= 0.01 and abs(amount - 1.8) >= 0.01:
                issues.append(
                    _('tasa ITBIS %(amount)s%% no estándar (18/16/0/1.8); asigne tipo_impuesto_webpos manualmente')
                    % {'amount': amount}
                )

        if tipo in self.ITBIS_TIPOS and tipo != '4' and not self._webpos_is_itbis_group() and not self._webpos_is_withholding():
            issues.append(
                _('tipo ITBIS WebPOS %(tipo)s requiere grupo con «ITBIS» en el nombre')
                % {'tipo': tipo}
            )

        if tipo == '4' and 'ITBIS' in gname and abs(amount) > 0.01:
            issues.append(_('tipo 4 (no facturable hoteles/rest.) no corresponde a ITBIS gravado'))

        if gname in ('ISR', 'RETENCIONES') and tipo in ('1', '2', '5', '6') and not self._webpos_is_withholding():
            issues.append(_('retención/ISR con tasa positiva y tipo ITBIS WebPOS inconsistente'))

        if gname == 'PROPINA' and tipo == '0' and abs(amount - 10.0) < 0.01:
            issues.append(_('propina 10%%: revise tipo WebPOS (no debe quedar en 0/Exento por defecto)'))

        if not issues and tipo == '0' and self._webpos_is_itbis_group() and abs(amount) >= 0.01:
            issues.append(
                _('sigue en tipo 0 (default) pero la tasa es %(amount)s%% — no fue configurado')
                % {'amount': amount}
            )

        return issues

    def _webpos_is_properly_configured(self):
        self.ensure_one()
        return not self._webpos_configuration_issues()

    @api.constrains('itx_tax_verified', 'tipo_impuesto_webpos', 'tax_group_id', 'amount', 'amount_type')
    def _check_webpos_tax_verified(self):
        for tax in self.filtered('itx_tax_verified'):
            issues = tax._webpos_configuration_issues()
            if issues:
                raise ValidationError(
                    _('No puede marcar «Verificado para WebPOS» en %(tax)s:\n- %(detail)s')
                    % {
                        'tax': tax.display_name,
                        'detail': '\n- '.join(issues),
                    }
                )
