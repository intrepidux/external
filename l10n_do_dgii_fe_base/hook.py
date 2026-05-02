import logging
_logger = logging.getLogger(__name__)
from odoo import SUPERUSER_ID, api


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info("XXXXXXXXXXXXXXXXXXXXXXXXXXX Ejecutando post_init_hook para actualizar los valores por defecto...XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
    _logger.debug("XXXXXXXXXXXXXXXXXXXXXXXXXXX Ejecutando post_init_hook para actualizar los valores por defecto...XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
    _logger.error("XXXXXXXXXXXXXXXXXXXXXXXXXXX Ejecutando post_init_hook para actualizar los valores por defecto...XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
 
    env['account.payment'].update_payment_defaults()