import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Re-canonicaliza qr_code (encf MAYÚSC) y recomputa sello en facturas."""
    env = api.Environment(cr, SUPERUSER_ID, {})
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

    _logger.info(
        'l10n_do_dgii_fe_base: migración QR encf upper | xml actualizados=%s moves=%s',
        updated_xml,
        len(moves),
    )
