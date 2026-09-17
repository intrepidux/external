# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    do_country = env.ref('base.do', raise_if_not_found=False)
    if not do_country:
        return
    journals = env['account.journal'].search(
        [
            ('l10n_latam_use_documents', '=', True),
            ('type', '=', 'purchase'),
            ('company_id.country_id', '=', do_country.id),
        ]
    )
    created = journals._bmc_ensure_webpos_credit_note_sequence()
    if created:
        _logger.info(
            'l10n_do_fix_report_invoice_bmc: created %s E34 sequence(s) on purchase journals',
            len(created),
        )
