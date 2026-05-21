from odoo import api, fields, models, _
from odoo.exceptions import UserError
import requests
import json
import base64
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class ItxFeDgii(models.Model):
    _name = 'itx.fe.dgii'
    _description = 'Maestro de Facturación Electrónica DGII'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nombre', required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Compañia', required=True, default=lambda self: self.env.company)
    rnc = fields.Char(string='RNC/Cédula', edit=False, help='RNC or Identification Number of the company', compute='_compute_rnc')

    @api.depends('company_id')
    def _compute_rnc(self):
        for record in self:
            record.rnc = record.company_id.vat if record.company_id else None

    # Fields for digital certificate
    certificate_file = fields.Binary(
        string='Certificado Digital (.p12/.pfx)',
        help='Digital certificate for DGII authentication (P12/PFX format)',
        attachment=True
    )
    certificate_filename = fields.Char(string='Nombre del Certificado')
    certificate_password = fields.Char(
        string='Contrasena del Certificado',
        help='Password for the digital certificate',
        # Removed password=True as it's deprecated in Odoo 17 model definitions
    )

    dgii_environment = fields.Selection([
        ('certecf', 'CerteCF'),
        ('testecf', 'TesteCF'),
        ('ecf', 'eCF Produccion')
    ], string='Ambiente DGII', default='certecf', required=True,
        help='Environment for DGII ECF submissions')

    api_base_url = fields.Char(
        string='URL Base de la API',
        required=True,
        help='Base URL for the external DGII API (e.g., https://api.yourdomain.com)'
    )

    dgii_client_mode = fields.Selection([
        ('prod', 'Produccion'),
        ('test', 'Test')
    ], string='Modo Cliente DGII', default='test', required=True,
        help='Client mode for DGII integration: Production or Test. Test mode uses mock endpoints or XSD validation.')

    dgii_validate_xsd = fields.Boolean(
        string='Validar XML con XSD',
        default=True,
        help='Si está activado, el XML generado será validado contra el esquema XSD de la DGII.'
    )

    is_test_mode = fields.Boolean(
        string='Es Modo Prueba',
        compute='_compute_is_test_mode',
        store=True,
        help='Indica si el modo cliente DGII actual es "test" o "produccion".' 
    )

    status_color = fields.Integer(compute='_compute_status_color')

    api_provisioning_key = fields.Char(
        string='Clave aprovisionamiento API',
        help='Debe coincidir con itx_dgii_api.provisioning_key en el servidor API.',
    )
    api_client_id = fields.Integer(
        string='ID cliente API (remoto)',
        readonly=True,
        copy=False,
    )
    api_key = fields.Char(
        string='API Key',
        copy=False,
        help='Generada al sincronizar con el servidor API. No compartir.',
    )
    api_sync_state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('synced', 'Sincronizado'),
            ('out_of_sync', 'Desactualizado'),
            ('error', 'Error'),
        ],
        string='Estado sync API',
        default='draft',
        readonly=True,
    )
    api_last_sync = fields.Datetime(string='Última sync API', readonly=True)
    api_sync_message = fields.Text(string='Mensaje sync API', readonly=True)
    cert_storage_mode = fields.Selection(
        [
            ('local_mirror', 'Espejo local + API'),
            ('remote_only', 'Solo en API'),
            ('local_legacy', 'Legacy (P12 en cada request, test)'),
        ],
        string='Almacenamiento certificado',
        default='local_mirror',
        required=True,
    )
    allow_inbound_fe = fields.Boolean(
        string='Receptor CerteCF (/fe)',
        default=True,
    )
    allow_inbound_auth = fields.Boolean(
        string='Autenticación inbound (/fe)',
        default=True,
    )
    url_recepcion = fields.Char(compute='_compute_fe_portal_urls', string='URL recepción')
    url_aprobacion_comercial = fields.Char(
        compute='_compute_fe_portal_urls',
        string='URL aprobación comercial',
    )
    url_autenticacion = fields.Char(
        compute='_compute_fe_portal_urls',
        string='URL autenticación (semilla)',
    )

    @api.depends('api_base_url')
    def _compute_fe_portal_urls(self):
        for rec in self:
            host = rec._fe_host_base()
            rec.url_recepcion = '%s/fe/recepcion/api/ecf' % host if host else ''
            rec.url_aprobacion_comercial = (
                '%s/fe/aprobacioncomercial/api/ecf' % host if host else ''
            )
            rec.url_autenticacion = (
                '%s/fe/autenticacion/api/semilla' % host if host else ''
            )

    def _fe_host_base(self):
        self.ensure_one()
        base = (self.api_base_url or '').rstrip('/')
        if base.endswith('/dgii/v1'):
            base = base[: -len('/dgii/v1')]
        return base

    def _certificate_b64(self):
        self.ensure_one()
        if not self.certificate_file:
            return None
        raw = self.certificate_file
        if isinstance(raw, bytes):
            return raw.decode('utf-8')
        return raw

    def _api_jsonrpc(self, path, params, *, use_api_key=False, use_provisioning=False, timeout=30):
        """POST JSON-RPC a la API DGII con cabeceras opcionales."""
        self.ensure_one()
        url = self.get_api_endpoint(path)
        headers = {'Content-Type': 'application/json'}
        if use_provisioning and self.api_provisioning_key:
            headers['X-Provisioning-Key'] = self.api_provisioning_key
        if use_api_key and self.api_key:
            headers['X-API-Key'] = self.api_key
        body = {
            'jsonrpc': '2.0',
            'method': 'call',
            'params': params,
            'id': 1,
        }
        response = requests.post(url, json=body, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get('error'):
            err = data['error']
            msg = err.get('message') if isinstance(err, dict) else str(err)
            raise UserError(_('DGII API: %s') % (msg or err))
        result = data.get('result') if isinstance(data, dict) else data
        return result if isinstance(result, dict) else {}

    def _require_synced_for_prod(self):
        self.ensure_one()
        if self.dgii_client_mode != 'prod':
            return
        if self.api_sync_state != 'synced' or not self.api_client_id or not self.api_key:
            raise UserError(
                _('En modo producción debe sincronizar con la API primero '
                  '(botón «Sincronizar con API»).')
            )

    def _sync_payload_base(self):
        self.ensure_one()
        cert_b64 = self._certificate_b64()
        if not cert_b64 or not self.certificate_password:
            raise UserError(_('Cargue certificado P12 y contraseña antes de sincronizar.'))
        if not self.api_provisioning_key:
            raise UserError(_('Configure la clave de aprovisionamiento API.'))
        rnc = (self.rnc or '').replace('-', '').strip()
        if not rnc:
            raise UserError(_('La compañía debe tener RNC (vat) configurado.'))
        return {
            'name': self.name,
            'rnc': rnc,
            'dgii_environment': self.dgii_environment or 'certecf',
            'certificate_b64': cert_b64,
            'certificate_password': self.certificate_password,
            'allow_outbound': True,
            'allow_inbound_fe': self.allow_inbound_fe,
            'allow_inbound_auth': self.allow_inbound_auth,
        }

    def action_sync_api_client(self):
        self.ensure_one()
        try:
            payload = self._sync_payload_base()
            if not self.api_client_id:
                result = self._api_jsonrpc(
                    'clients/register',
                    payload,
                    use_provisioning=True,
                    timeout=60,
                )
            else:
                payload['client_id'] = self.api_client_id
                result = self._api_jsonrpc(
                    'clients/update_certificate',
                    payload,
                    use_provisioning=True,
                    timeout=60,
                )
            if not result.get('success'):
                self.write({
                    'api_sync_state': 'error',
                    'api_sync_message': result.get('error') or _('Error desconocido'),
                })
                raise UserError(result.get('error') or _('Sync API falló.'))
            vals = {
                'api_client_id': result.get('client_id') or self.api_client_id,
                'api_sync_state': 'synced',
                'api_last_sync': fields.Datetime.now(),
                'api_sync_message': _('OK'),
            }
            if result.get('api_key'):
                vals['api_key'] = result['api_key']
            self.write(vals)
            if self.cert_storage_mode == 'remote_only':
                self.write({
                    'certificate_file': False,
                    'certificate_filename': False,
                    'certificate_password': False,
                })
            msg = _('Sincronizado. client_id=%s') % self.api_client_id
            if result.get('api_key'):
                msg += '\n' + _('API Key (guárdela): %s') % result['api_key']
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync API'),
                    'message': msg,
                    'sticky': bool(result.get('api_key')),
                    'type': 'success',
                },
            }
        except UserError:
            raise
        except Exception as e:
            self.write({
                'api_sync_state': 'error',
                'api_sync_message': str(e),
            })
            raise UserError(_('Error al sincronizar con API: %s') % e) from e

    def _api_params_with_auth(self, extra=None):
        """Params para /dgii/v1 en prod (client_id) o legacy test."""
        self.ensure_one()
        params = dict(extra or {})
        if self._use_legacy_cert_in_request():
            cert_b64 = self._certificate_b64()
            if cert_b64:
                params['certificate_b64'] = cert_b64
                params['certificate_password'] = self.certificate_password
            params['rnc'] = (self.rnc or '').replace('-', '').strip()
        else:
            self._require_synced_for_prod()
            params['client_id'] = self.api_client_id
            if self.rnc:
                params['rnc'] = (self.rnc or '').replace('-', '').strip()
        if self.dgii_environment:
            env_map = {
                'certecf': 'CerteCF',
                'testecf': 'TesteCF',
                'ecf': 'eCF',
            }
            params.setdefault('environment', env_map.get(self.dgii_environment, 'CerteCF'))
        return params

    def _use_legacy_cert_in_request(self):
        self.ensure_one()
        if self.cert_storage_mode == 'local_legacy':
            return True
        if self.dgii_client_mode == 'test' and self.api_sync_state != 'synced':
            return True
        return False

    @api.depends('dgii_client_mode', 'active')
    def _compute_status_color(self):
        for rec in self:
            if not rec.active:
                rec.status_color = 0  # Inactivo (muted)
            elif rec.dgii_client_mode == 'test':
                rec.status_color = 3  # Test (warning)
            else:
                rec.status_color = 5  # Produccion (success)

    @api.depends('dgii_client_mode')
    def _compute_is_test_mode(self):
        for rec in self:
            rec.is_test_mode = (rec.dgii_client_mode == 'test')

    @api.constrains('dgii_environment', 'dgii_client_mode')
    def _check_prod_environment(self):
        for rec in self:
            if rec.dgii_client_mode == 'prod' and rec.dgii_environment not in ['ecf']:
                # raise ValidationError("En modo producción, el ambiente DGII debe ser 'eCF Produccion'.")
                pass # Eliminado por ahora para depuración

    def write(self, vals):
        res = super().write(vals)
        watch = {'certificate_file', 'certificate_password', 'dgii_environment', 'allow_inbound_fe', 'allow_inbound_auth'}
        if watch.intersection(vals.keys()):
            self.filtered(lambda r: r.api_sync_state == 'synced').write({
                'api_sync_state': 'out_of_sync',
                'api_sync_message': _('Certificado o configuración cambiaron; sincronice de nuevo.'),
            })
        return res

    def get_api_endpoint(self, path):
        self.ensure_one()
        base_url = self.api_base_url.rstrip('/')
        path = path.lstrip('/')
        return f"{base_url}/dgii/v1/{path}"

    def get_mode_description(self):
        self.ensure_one()
        if self.dgii_client_mode == 'test':
            return "Modo Prueba: Las facturas NO se enviaran a DGII real. Solo se generara XML y se validara contra esquema XSD."
        return f"Modo Produccion: Las facturas se enviaran a DGII real. Ambiente: {self.dgii_environment}"

    def action_test_connection(self):
        self.ensure_one()
        try:
            params = {}
            use_key = self.api_sync_state == 'synced' and bool(self.api_key)
            if use_key:
                params['client_id'] = self.api_client_id
            result = self._api_jsonrpc(
                'test',
                params,
                use_api_key=use_key,
                timeout=10,
            )
            if result.get('status') == 'ok':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Conexion Exitosa',
                        'message': f'Conectado a la API en {self.api_base_url}',
                        'type': 'success',
                    }
                }
            api_message = result.get('message', 'N/A')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error de Conexion',
                    'message': _('La API respondió pero el estado no es OK: %s') % api_message,
                    'type': 'danger',
                },
            }
        except requests.exceptions.ConnectionError:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error de Conexion',
                    'message': f'No se pudo conectar a la API en {self.api_base_url}. Verifique la URL y la conectividad.',
                    'type': 'danger',
                }
            }
        except requests.exceptions.Timeout:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Timeout',
                    'message': f'Tiempo de espera agotado al conectar con la API en {self.api_base_url}.',
                    'type': 'danger',
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error Inesperado',
                    'message': f'Ocurrio un error inesperado al probar la conexion: {str(e)}',
                    'type': 'danger',
                }
            }


    def _api_error_message(self, payload):
        """Mensaje de error de respuesta JSON /dgii/v1 (campo error o message)."""
        if not isinstance(payload, dict):
            return _('Error desconocido')
        return (
            payload.get('error')
            or payload.get('message')
            or _('Error desconocido')
        )

    def action_validate_certificate(self):
        """Validar certificado digital llamando a la API."""
        self.ensure_one()

        _logger.debug("Entering action_validate_certificate.")
        _logger.debug("Certificate file exists: %s, password exists: %s, filename: %s",
                      bool(self.certificate_file), bool(self.certificate_password), self.certificate_filename)

        use_remote_cert = (
            self.api_sync_state == 'synced'
            and self.api_client_id
            and self.api_key
        )

        if not use_remote_cert:
            if not self.certificate_file:
                _logger.debug("No certificate file found, returning warning.")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Certificado Requerido',
                        'message': 'Debe cargar un certificado digital (.p12/.pfx)',
                        'type': 'warning',
                    }
                }

            if not self.certificate_password:
                _logger.debug("No certificate password found, returning warning.")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Contraseña Requerida',
                        'message': 'Debe proporcionar la contraseña del certificado',
                        'type': 'warning',
                    }
                }

        try:
            if use_remote_cert:
                api_response_data = self._api_jsonrpc(
                    'validate_certificate',
                    {'client_id': self.api_client_id},
                    use_api_key=True,
                    timeout=30,
                )
            else:
                cert_b64 = self._certificate_b64()
                api_response_data = self._api_jsonrpc(
                    'validate_certificate',
                    {
                        'certificate_b64': cert_b64,
                        'certificate_password': self.certificate_password,
                    },
                    timeout=30,
                )

            if api_response_data.get('valid'):
                _logger.debug("Certificate validated successfully.")
                cert_info = api_response_data.get('certificate_info', {})
                subject = cert_info.get('subject', 'N/A')
                expiry = cert_info.get('not_after', 'N/A')

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Certificado Valido',
                        'message': f'Certificado y contraseña correctos.\nSubject: {subject}\nVence: {expiry}',
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                _logger.debug("Certificate validation failed. API Result: %s", api_response_data)
                error_msg = self._api_error_message(api_response_data)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Certificado Invalido',
                        'message': f'No se pudo validar el certificado: {error_msg}',
                        'sticky': True,
                        'type': 'danger',
                    }
                }

        except requests.exceptions.Timeout:
            _logger.debug("API Request Timeout.")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Timeout',
                    'message': 'La API no respondio en 30 segundos',
                    'type': 'danger',
                }
            }
        except requests.exceptions.ConnectionError:
            _logger.debug("API Connection Error for URL: %s", self.api_base_url)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error de Conexion',
                    'message': _('No se pudo conectar a la API en %s.') % self.api_base_url,
                    'type': 'danger',
                }
            }
        except Exception as e:
            _logger.debug("Unexpected Error during certificate validation: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error al validar certificado: {str(e)}',
                    'type': 'danger',
                }
            }
