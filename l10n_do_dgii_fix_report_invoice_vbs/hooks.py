# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(cr, registry):
    """Generate missing ECF sequences for existing fiscal journals.

    When the module is installed/updated, existing journals that use
    l10n_latam documents and belong to Dominican Republic companies
    with ECF enabled may not have sequences for electronic document
    types (E41, E44, etc.). This hook regenerates the missing sequences.
    """
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info(
        "[post_init_hook] Regenerating fiscal sequences for existing ECF companies..."
    )

    companies = env["res.company"].search(
        [
            ("country_id.code", "=", "DO"),
            ("l10n_do_ecf_issuer", "=", True),
        ]
    )

    _logger.info(
        "[post_init_hook] Found %d DO companies with ECF enabled",
        len(companies),
    )

    for company in companies:
        # Determine effective mode
        mode = company.l10n_do_fiscal_sequence_mode or "b"
        _logger.info(
            "[post_init_hook] Processing company %s (mode=%s)",
            company.name,
            mode,
        )

        if mode in ("e", "both"):
            env["account.journal"].generate_missing_fiscal_sequences_for_company(
                company
            )
            _logger.info(
                "[post_init_hook] Generated missing sequences for company %s",
                company.name,
            )
        else:
            _logger.info(
                "[post_init_hook] Company %s mode=%s, skipping ECF sequences",
                company.name,
                mode,
            )

    _logger.info("[post_init_hook] Finished regenerating fiscal sequences.")