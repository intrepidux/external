import logging

_logger = logging.getLogger(__name__)


def _audit_webpos_taxes(env):
    taxes = env['account.tax'].search([('active', '=', True)])
    misconfigured = taxes.filtered(lambda t: t._webpos_configuration_issues())
    wrongly_verified = misconfigured.filtered('itx_tax_verified')
    if wrongly_verified:
        wrongly_verified.write({'itx_tax_verified': False})
        _logger.warning(
            'l10n_do_fix_report_invoice_bmc: cleared itx_tax_verified on %s misconfigured taxes',
            len(wrongly_verified),
        )
    return misconfigured


def post_init_hook(cr, registry):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    misconfigured = _audit_webpos_taxes(env)
    for tax in misconfigured[:15]:
        _logger.warning(
            'WebPOS tax audit [%s] amount=%s tipo=%s group=%s → %s',
            tax.display_name,
            tax.amount,
            tax.tipo_impuesto_webpos,
            tax.tax_group_id.name,
            '; '.join(tax._webpos_configuration_issues()),
        )