import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_do_dgii_fe_base.models.itx_xml_data_dgii import (
    ICP_QR_STAMP_V2,
    ICP_QR_STAMP_V3,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Normaliza qr_code legacy (doble url_quote_plus) y recomputa sello en facturas."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    icp = env['ir.config_parameter'].sudo()
    if icp.get_param(ICP_QR_STAMP_V2) == 'True' and icp.get_param(ICP_QR_STAMP_V3) == 'True':
        _logger.info('l10n_do_dgii_fe_base: migración QR v2/v3 ya aplicada, omitiendo')
        return

    Xml = env['itx.xml.data.dgii'].sudo()
    updated_xml = 0
    for xml in Xml.search([('qr_code', '!=', False)]):
        old = (xml.qr_code or '').strip()
        if not old:
            continue
        canonical = xml._canonical_qr_stamp_url()
        if canonical and canonical != old:
            xml.write({'qr_code': canonical})
            updated_xml += 1

    Move = env['account.move'].sudo()
    moves = Move.search([('itx_xml_data_id', '!=', False)])
    if moves:
        moves._compute_itx_dgii_electronic_stamp()

    icp.set_param(ICP_QR_STAMP_V2, 'True')
    icp.set_param(ICP_QR_STAMP_V3, 'True')
    _logger.info(
        'l10n_do_dgii_fe_base: migración QR v2/v3 | xml actualizados=%s moves=%s',
        updated_xml,
        len(moves),
    )
