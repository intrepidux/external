# -*- coding: utf-8 -*-


def post_init_hook(env):
    """Ensure E34 (e-credit_note) fiscal sequence on purchase fiscal journals."""
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
    journals._bmc_ensure_webpos_credit_note_sequence()
