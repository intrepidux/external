# -*- coding: utf-8 -*-

import json

from markupsafe import escape

from odoo.http import Controller, request, route


class WebposDgiiController(Controller):

    @route(['/webpos/dgii_qr/<int:move_id>'], type='http', auth='user')
    def open_dgii_qr(self, move_id, **kwargs):
        """DGII (Citrix) returns 404 when Referer is an external/Odoo domain."""
        move = request.env['account.move'].browse(move_id).exists()
        if not move:
            return request.not_found()
        move.check_access_rights('read')
        move.check_access_rule('read')
        url = move._webpos_get_dgii_qr_url()
        if not url:
            return request.not_found()

        safe_url = escape(url)
        js_url = json.dumps(url)
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <meta name="referrer" content="no-referrer"/>
    <title>Redirigiendo a DGII...</title>
</head>
<body>
    <p>Redirigiendo a DGII...</p>
    <p><a href="{safe_url}" rel="noreferrer noopener">Abrir DGII</a></p>
    <script>window.location.replace({js_url});</script>
</body>
</html>"""
        return request.make_response(
            html,
            headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('Referrer-Policy', 'no-referrer'),
                ('Cache-Control', 'no-store'),
            ],
        )
