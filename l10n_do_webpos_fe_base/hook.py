import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.payment'].update_payment_defaults()
    env['webpos.gate']._register_client_with_api()
