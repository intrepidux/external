from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging
import requests

_logger = logging.getLogger(__name__)


class WebposGate(models.AbstractModel):
    _name = 'webpos.gate'
    _description = 'WebPOS Gate for RNC based blocking'

    @api.model
    def _get_webpos_api_base_url(self):
        """Obtiene la URL base del API WebPOS desde los parámetros del sistema."""
        return self.env['ir.config_parameter'].sudo().get_param('webpos_api.base_url', 'http://localhost:8069')

    @api.model
    def _register_api_url(self):
        """URL de registro alineada con webpos_api.base_url (…/webpos → …/webpos/register)."""
        base = (self._get_webpos_api_base_url() or '').rstrip('/')
        if base.endswith('/webpos'):
            return f'{base}/register'
        return f'{base}/webpos/register'

    @api.model
    def _collect_webpos_rnc_list(self):
        """
        RNC únicos de esta instancia Odoo (multi-compañía).

        Una compañía suele tener diario de venta y de compra; comparten el mismo NIF.
        Registramos cada res.company con VAT: el API empuja por RNC y el bloqueo local
        solo aplica a movimientos en diarios is_webpos.
        """
        Company = self.env['res.company'].sudo()
        rnc_by_company = {}
        for company in Company.search([]):
            if not company.vat:
                continue
            rnc = self._normalize_rnc(company.vat)
            if rnc:
                rnc_by_company[company.id] = rnc

        rnc_list = sorted(rnc_by_company.values())
        if rnc_list:
            names = Company.browse(list(rnc_by_company.keys())).mapped('name')
            _logger.info('WebPOS Gate: RNCs %s — compañías: %s', rnc_list, ', '.join(names))
        else:
            _logger.warning('WebPOS Gate: ninguna compañía con NIF/RNC configurado.')
        return rnc_list

    @api.model
    def _register_client_with_api(self):
        """Registra esta instancia Odoo en el API (push gate por RNC)."""
        ICP = self.env['ir.config_parameter'].sudo()
        register_url = self._register_api_url()
        web_base_url = ICP.get_param('web.base.url')
        if not web_base_url:
            _logger.error('WebPOS Gate: web.base.url vacío; no se puede registrar en API.')
            return False

        payload = {
            'web_base_url': web_base_url,
            'db_uuid': ICP.get_param('database.uuid'),
            'db_name': self.env.cr.dbname,
            'rnc_list': self._collect_webpos_rnc_list(),
        }
        _logger.info('WebPOS Gate: registrando instancia en %s con RNCs %s', register_url, payload['rnc_list'])
        try:
            response = requests.post(register_url, json=payload, timeout=30)
            response.raise_for_status()
            body = response.json()
            if body.get('success'):
                _logger.info('WebPOS Gate: registro en API OK (instance_id=%s).', body.get('instance_id'))
                return True
            _logger.error('WebPOS Gate: API rechazó registro: %s', body.get('error', body))
            return False
        except requests.exceptions.RequestException as exc:
            _logger.error('WebPOS Gate: error HTTP al registrar en API: %s', exc)
            return False
        except Exception:
            _logger.exception('WebPOS Gate: error inesperado al registrar en API.')
            return False

    @api.model
    def _normalize_rnc(self, rnc_value):
        """Normaliza el RNC/VAT dejando solo dígitos."""
        return ''.join(c for c in (rnc_value or '') if c.isdigit())

    @api.model
    def _normalize_ambiente_key(self, ambiente_value):
        """Clave de cache: test | prod | both (alineado con API)."""
        raw = (ambiente_value or '').strip().lower()
        if not raw:
            return 'both'
        if any(token in raw for token in ('test', 'prueba', 'cert', 'mock', 'desarrollo', 'dev', 'qa')):
            return 'test'
        if any(token in raw for token in ('prod', 'produ', 'live', 'real', 'comercial')):
            return 'prod'
        return 'both'

    @api.model
    def _webpos_ambiente_for_company(self, company):
        cred = company.fe_webpos_id.filtered(lambda c: c.active)[:1]
        return self._normalize_ambiente_key(cred.name if cred else '')

    @api.model
    def _webpos_gate_is_active(self):
        """Retorna True si el gate está habilitado y hay algún RNC bloqueado."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('webpos.gate.check_enabled') != 'True':
            return False
        by_rnc = self._webpos_gate_load_by_rnc()
        return bool(self._any_blocked_in_cache(by_rnc))

    @api.model
    def _any_blocked_in_cache(self, by_rnc_data):
        for entry in (by_rnc_data or {}).values():
            if not isinstance(entry, dict):
                continue
            if entry.get('blocked'):
                return True
            for amb_key in ('test', 'prod', 'both'):
                sub = entry.get(amb_key)
                if isinstance(sub, dict) and sub.get('blocked'):
                    return True
        return False

    @api.model
    def _webpos_gate_load_by_rnc(self):
        """Carga el JSON de RNCs bloqueados desde los parámetros del sistema."""
        ICP = self.env['ir.config_parameter'].sudo()
        by_rnc_json = ICP.get_param('webpos.gate.by_rnc', '{}')
        try:
            return json.loads(by_rnc_json)
        except json.JSONDecodeError:
            _logger.error("Error al parsear JSON de webpos.gate.by_rnc: %s", by_rnc_json)
            return {}

    @api.model
    def _webpos_gate_message_for_company(self, company, by_rnc_data=None):
        """Obtiene el mensaje de bloqueo para una compañía (RNC + ambiente FE activo)."""
        if not company or not company.vat:
            return None

        normalized_rnc = self._normalize_rnc(company.vat)
        if not normalized_rnc:
            return None

        if by_rnc_data is None:
            by_rnc_data = self._webpos_gate_load_by_rnc()

        ambiente = self._webpos_ambiente_for_company(company)
        rnc_entry = by_rnc_data.get(normalized_rnc, {})
        if not isinstance(rnc_entry, dict):
            return None

        # Formato legacy (sin ambiente)
        if 'blocked' in rnc_entry:
            if rnc_entry.get('blocked'):
                return rnc_entry.get('message') or _('Operaciones WebPOS suspendidas para esta compañía.')
            return None

        for key in (ambiente, 'both'):
            sub = rnc_entry.get(key)
            if isinstance(sub, dict) and sub.get('blocked'):
                return sub.get('message') or _('Operaciones WebPOS suspendidas para esta compañía.')
        return None

    @api.model
    def _webpos_gate_assert_moves_operable(self, moves):
        """Hook para action_post: verifica si los moves están operables según el gate."""
        if not self._webpos_gate_is_active():
            return

        webpos_moves = moves.filtered(lambda m: m.journal_id.is_webpos)
        if not webpos_moves:
            return

        by_rnc_data = self._webpos_gate_load_by_rnc()
        for move in webpos_moves:
            msg = self._webpos_gate_message_for_company(move.company_id, by_rnc_data)
            if msg:
                raise UserError(msg)

    @api.model
    def _apply_gate_updates(self, updates):
        """
        Aplica las actualizaciones de estado del gate recibidas del API.
        `updates` es una lista de diccionarios con {'rnc', 'blocked', 'status', 'message'}.
        """
        _logger.info("Aplicando actualizaciones del gate WebPOS: %s", updates)
        ICP = self.env['ir.config_parameter'].sudo()
        current_by_rnc = self._webpos_gate_load_by_rnc()

        for update in updates:
            rnc = self._normalize_rnc(update.get('rnc'))
            if not rnc:
                continue
            ambiente = update.get('ambiente') or 'both'
            if ambiente not in ('test', 'prod', 'both'):
                ambiente = self._normalize_ambiente_key(ambiente)

            bucket = current_by_rnc.setdefault(rnc, {})
            if 'blocked' in bucket and ambiente != 'both':
                bucket = current_by_rnc[rnc] = {}
            bucket[ambiente] = {
                'blocked': update.get('blocked', False),
                'message': update.get('message', ''),
                'status': update.get('status', 'active'),
            }

        has_blocked_any = self._any_blocked_in_cache(current_by_rnc)
        ICP.set_param('webpos.gate.by_rnc', json.dumps(current_by_rnc))
        ICP.set_param('webpos.gate.has_blocked', str(has_blocked_any))
        ICP.set_param('webpos.gate.last_sync', fields.Datetime.now().isoformat())
        _logger.info("Actualizaciones del gate WebPOS aplicadas. Bloqueados: %s", has_blocked_any)
