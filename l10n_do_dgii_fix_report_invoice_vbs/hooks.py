# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Generate missing ECF sequences; clean orphan FE views if fe_base absent."""
    fe_mod = env["ir.module.module"].search(
        [("name", "=", "l10n_do_dgii_fe_base")], limit=1
    )
    if fe_mod.state != "installed":
        try:
            from odoo.addons.l10n_do_dgii_fe_base.fe_ui_cleanup import (
                cleanup_orphan_dgii_fe_ui,
            )

            cleanup_orphan_dgii_fe_ui(env)
        except ImportError:
            _logger.warning(
                "[post_init_hook] l10n_do_dgii_fe_base not on addons path; "
                "orphan FE invoice views were not cleaned."
            )

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