# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)

_FE_VIEW_MARKERS = (
    'itx_dgii_dgi_status',
    'itx_xml_data_ids',
    'itx_dgii_xml_name',
)


def cleanup_orphan_dgii_fe_ui(env):
    """Remove FE invoice views if this module is not installed (stale DB)."""
    mod = env['ir.module.module'].search([('name', '=', 'l10n_do_dgii_fe_base')], limit=1)
    if mod.state == 'installed':
        return

    View = env['ir.ui.view'].with_context(active_test=False)
    Data = env['ir.model.data']
    to_unlink = View.browse()

    for marker in _FE_VIEW_MARKERS:
        for view in View.search([('model', '=', 'account.move'), ('arch_db', 'ilike', marker)]):
            data = Data.search([('model', '=', 'ir.ui.view'), ('res_id', '=', view.id)], limit=1)
            if not data or data.module == 'l10n_do_dgii_fe_base':
                to_unlink |= view

    for xmlid in (
        'l10n_do_dgii_fe_base.itx_account_move_inherit',
        'l10n_do_dgii_fe_base.view_account_move_dgii_tree',
    ):
        try:
            to_unlink |= env.ref(xmlid)
        except ValueError:
            pass

    if to_unlink:
        _logger.info(
            'l10n_do_dgii_fe_base: removing orphan DGII FE views: %s',
            ', '.join(sorted(set(to_unlink.mapped('name')))),
        )
        to_unlink.unlink()
