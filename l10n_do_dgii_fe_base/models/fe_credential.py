from odoo import api, fields, models
import requests
import json
import base64
import os
import tempfile
import logging # Asegurarse de que logging esté importado

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

    is_test_mode = fields.Boolean(
        string='Es Modo Prueba',
        compute='_compute_is_test_mode',
        store=True,
        help='Indica si el modo cliente DGII actual es "test" o "produccion".' 
    )

    status_color = fields.Integer(compute='_compute_status_color')

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

    def get_api_endpoint(self, path):
        self.ensure_one()
        base_url = self.api_base_url.rstrip('/')
        if self.dgii_client_mode == 'test':
            return f"{base_url}/dgii/test/v1/{path}"
        return f"{base_url}/dgii/v1/{path}"

    def get_mode_description(self):
        self.ensure_one()
        if self.dgii_client_mode == 'test':
            return "Modo Prueba: Las facturas NO se enviaran a DGII real. Solo se generara XML y se validara contra esquema XSD."
        return f"Modo Produccion: Las facturas se enviaran a DGII real. Ambiente: {self.dgii_environment}"

    def action_test_connection(self):
        self.ensure_one()
        api_url = self.get_api_endpoint('test')
        result = {} # Inicializar result
        try:
            response = requests.post(api_url, json={}, timeout=5)
            _logger.debug("API raw response for connection test: %s", response.text) # <-- AÑADIDO
            response.raise_for_status()
            try:
                result = response.json()
                _logger.debug("API JSON response for connection test: %s", result) # <-- MOVIDO Y CORREGIDO
            except json.JSONDecodeError:
                _logger.error("API Response is not a valid JSON: %s", response.text)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error de Conexion',
                        'message': f'La API respondió con contenido no JSON: {response.text[:100]}...',
                        'type': 'danger',
                    }
                }

            if result.get('result', {}).get('status') == 'ok':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Conexion Exitosa',
                        'message': f'Conectado a la API en {self.api_base_url}',
                        'type': 'success',
                    }
                }
            else:
                # Acceder correctamente al mensaje anidado
                api_message = result.get('result', {}).get('message', 'N/A')
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error de Conexion',
                        'message': f'La API respondio, pero el estado no es OK. Mensaje: {api_message}',
                        'type': 'danger',
                    }
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


    def action_validate_certificate(self):
        """Validar certificado digital llamando a la API."""
        self.ensure_one()

        _logger.debug("Entering action_validate_certificate.")
        _logger.debug("Certificate file exists: %s, password exists: %s, filename: %s",
                      bool(self.certificate_file), bool(self.certificate_password), self.certificate_filename)

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

        # Obtener URL del endpoint
        api_url = self.get_api_endpoint('validate_certificate')
        _logger.debug("API Endpoint URL: %s", api_url)

        # Preparar certificado en base64
        cert_b64 = self.certificate_file.decode('utf-8') if isinstance(self.certificate_file, bytes) else self.certificate_file
        _logger.debug("Certificate base64 prepared. Length: %s, Prefix: %s",
                      len(cert_b64) if cert_b64 else 0, cert_b64[:50] if cert_b64 else "N/A")

        payload = {
            'certificate_b64': cert_b64,
            'certificate_password': self.certificate_password,
        }
        _logger.debug("Payload before sending request. Cert B64 Len: %s, Password Len: %s, Cert B64 Prefix: %s",
                      len(payload.get('certificate_b64', '')) if payload.get('certificate_b64') else 0,
                      len(payload.get('certificate_password', '')) if payload.get('certificate_password') else 0,
                      payload.get('certificate_b64', '')[:50] if payload.get('certificate_b64') else "N/A")

        headers = {'Content-Type': 'application/json'}

        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            _logger.debug("API Response Status: %s, Response Text: %s", response.status_code, response.text[:200])
            response.raise_for_status()
            result = response.json()
            _logger.debug("API Response JSON: %s", result)

            if result.get('success') and result.get('valid'):
                _logger.debug("Certificate validated successfully.")
                cert_info = result.get('certificate_info', {})
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
                _logger.debug("Certificate validation failed. API Result: %s", result)
                error_msg = result.get('message', 'Error desconocido')
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
            _logger.debug("API Connection Error for URL: %s", api_url)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error de Conexion',
                    'message': f'No se pudo conectar a la API en {api_url}. Verifique la URL y la conectividad.',
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
