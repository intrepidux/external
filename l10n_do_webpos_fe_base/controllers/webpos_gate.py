import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WebposGateController(http.Controller):
    """Recibe actualizaciones de estado del gate WebPOS desde el API."""

    @http.route('/webpos/gate/update_status', type='http', auth='none', methods=['POST'], csrf=False)
    def update_status(self, **kw):
        _logger.info("WebPOS Gate: Recibida solicitud de actualización de estado.")
        try:
            raw = request.httprequest.data or b'{}'
            data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except (ValueError, TypeError):
            _logger.error("WebPOS Gate: JSON inválido recibido.")
            return request.make_response(
                json.dumps({'success': False, 'error': 'invalid_json'}),
                headers=[('Content-Type', 'application/json')],
                status=400,
            )

        updates = data.get('updates')
        if not updates or not isinstance(updates, list):
            _logger.warning("WebPOS Gate: No se encontraron actualizaciones válidas en el payload.")
            return request.make_response(
                json.dumps({'success': False, 'error': 'no_valid_updates'}),
                headers=[('Content-Type', 'application/json')],
                status=400,
            )

        try:
            request.env['webpos.gate'].sudo()._apply_gate_updates(updates)
            request.env.cr.commit()
            _logger.info("WebPOS Gate: Actualización de estado aplicada exitosamente.")
            return request.make_response(
                json.dumps({'success': True}),
                headers=[('Content-Type', 'application/json')],
            )
        except Exception as e:
            _logger.exception("WebPOS Gate: Error al aplicar actualizaciones de estado.")
            request.env.cr.rollback()
            return request.make_response(
                json.dumps({'success': False, 'error': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=500,
            )
