from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import requests
import logging
import base64
import json
from datetime import datetime, date
#from odoo.addons.l10n_do_dgii_fe_base.utils.xml_base import XmlInterface

_logger = logging.getLogger(__name__)


def _post_dgii_json_route(url, params_dict, timeout=30):
    """
    POST a rutas Odoo type='json': el servidor espera JSON-RPC 2.0 con params.
    Si se envía JSON plano, request.jsonrequest puede quedar vacío y el controlador ve {}.
    """
    body = {
        'jsonrpc': '2.0',
        'method': 'call',
        'params': params_dict,
        'id': 1,
    }
    response = requests.post(
        url,
        json=body,
        headers={'Content-Type': 'application/json'},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        return data
    if data.get('error'):
        err = data['error']
        msg = None
        if isinstance(err, dict):
            msg = err.get('message')
            nested = err.get('data')
            if isinstance(nested, dict) and nested.get('message'):
                msg = nested['message']
            elif isinstance(nested, str):
                msg = nested
        if not msg:
            msg = str(err)
        raise UserError(_('DGII API: %s') % msg)
    result = data.get('result')
    return result if isinstance(result, dict) else {}


class ItxXMLDataDGII(models.Model):
    _name = 'itx.xml.data.dgii'
    _description = 'Maneja el procesamiento de documento XML para DGII'
    
    _prefijo_factura = 'F'
    _prefijo_nota_credito = 'C'
    _prefijo_nota_debito = 'D'
    _prefijo_no_fiscal = 'N'
    
    name = fields.Char(string='Name')
    xml_data = fields.Text(string='XML Data', default="<xml> probando</xml>")
    status = fields.Selection([
        ('pending', 'Por enviar'),
        ('sent', 'Enviado'),
        ('error', 'Error'),
        ('procesed', 'Procesado')
    ], default='pending', string='Status')
    state = fields.Selection([('to_send', 'To Send'), ('sent', 'Sent'), ('to_cancel', 'To Cancel'), ('cancelled', 'Cancelled')])
    error = fields.Text(string='Error Message')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    account_move_id = fields.Many2one('account.move', string='Cuenta de Movimiento', ondelete='cascade')
    l10n_do_ncf_type = fields.Char(string='l10n_do_ncf_type')
 
    # Field for binary download
    xml_file_binary = fields.Binary(string="XML File", compute='_compute_xml_file_binary', store=False)

    @api.depends('xml_data')
    def _compute_xml_file_binary(self):
        for record in self:
            if record.xml_data:
                record.xml_file_binary = base64.b64encode(record.xml_data.encode('utf-8'))
            else:
                record.xml_file_binary = False

    # Campos de dgii.document response api
    cufe = fields.Char(string='CUFE', default='NOT SET')
    doc_type = fields.Char(string='Tipo de Documento', default='NOT SET')
    doc_date = fields.Date(string='Fecha de Documento')
    company_lic_cod = fields.Char(string='Código de Licencia', default='NOT SET')
    company_ruc = fields.Char(string='RUC de la Empresa', default='NOT SET')
    branch_cod = fields.Char(string='Código de Sucursal', default='NOT SET')
    pos_cod = fields.Char(string='Código de POS', default='NOT SET')
    fe_number = fields.Char(string='Número FE', default='NOT SET')
    authorized = fields.Boolean(string='Autorizado')
    auth_number = fields.Char(string='Número de Autorización', default='NOT SET')
    auth_date = fields.Date(string='Fecha de Autorización')
    xml = fields.Text(string="XML ECF")
    pdf = fields.Binary(string='PDF Data')
    date_rec = fields.Date(string='Fecha de Recepción')
    system_ref = fields.Char(string='Referencia del Sistema', default='NOT SET')
    doc_affected_ref = fields.Char(string='Referencia del Documento Afectado', default='NOT SET')
    sub_doc_type = fields.Char(string='Subtipo de Documento', default='NOT SET')

    qr_code = fields.Char(string="QR Code")
    qr_l1 = fields.Char(string="Código de Seguridad")
    qr_l2 = fields.Char(string="Fecha Firma Digital")
    xml_dgii = fields.Text(string="XML DGII")
    sub_total = fields.Float(string="Subtotal")
    tax_total = fields.Float(string="Total de ITBIS")
    total = fields.Float(string="Monto Total")
    sbt0 = fields.Float(string="Subtotal 0")
    sbt1 = fields.Float(string="Subtotal 1")
    sbt2 = fields.Float(string="Subtotal 2")
    sbt3 = fields.Float(string="Subtotal 3")
    tax1 = fields.Float(string="Impuesto 1")
    tax2 = fields.Float(string="Impuesto 2")
    tax3 = fields.Float(string="Impuesto 3")
    dgi_resp = fields.Text(string="Respuesta DGI")
    dgi_err_msg = fields.Text(string="Mensaje de Error DGI")
    sts = fields.Integer(string="Estado")
    dgi_sts = fields.Integer(string="Estado DGI")
    dgi_status = fields.Char(string="Estado DGI (Texto)", default="NO ENVIADO")
    json_response_sent = fields.Text(string='Res JSON(envio)')
    json_response = fields.Text(string='Res JSON(recibido)')

    # DGII Direct Integration Fields
    track_id = fields.Char(
        string='Track ID (DGII)',
        help='Tracking ID returned by DGII for status verification',
        index=True
    )
    signature = fields.Char(
        string='Código de Seguridad',
        help='6-character security code from signed XML',
        size=6
    )
    signed_xml = fields.Text(
        string='XML Firmado',
        help='The digitally signed XML document'
    )
    dgii_auth_number = fields.Char(
        string='Número de Autorización DGII',
        help='Authorization number returned by DGII upon approval'
    )

    def _serialize_datetime_data(self, data):
        """
        Recursively convert datetime objects to strings in nested data structures
        to ensure JSON serialization compatibility.
        """
        if isinstance(data, (datetime, date)):
            return data.strftime('%Y-%m-%d %H:%M:%S') if isinstance(data, datetime) else data.strftime('%Y-%m-%d')
        elif isinstance(data, dict):
            return {key: self._serialize_datetime_data(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._serialize_datetime_data(item) for item in data]
        elif isinstance(data, tuple):
            return tuple(self._serialize_datetime_data(item) for item in data)
        else:
            return data

    # @api.model
    # def create(self, vals):
    #     try:
    #         # Crea el registro usando el método padre
    #         record = super(ItxXMLDataDGII, self).create(vals)
            
    #         # Guarda y envía el XML
    #         self.save_and_send_xml()
            
    #         # Registro en el log
    #         _logger.info(f'Registro creado: {record.id}')
            
    #         return record
    #     except Exception as e:
    #         _logger.error(f'Error al crear el registro xml.data: {e}')
    #         raise  
    
    
    
    def action_download_json(self):
        self.ensure_one()  # Asegúrate de que solo haya un registro
        json_data = self.json_response
        
        if not json_data:
            raise UserError("No hay datos JSON para descargar.")

        # Convertir el texto JSON a bytes
        json_bytes = json_data.encode('utf-8')
        
        # Crear el archivo base64 para la descarga
        json_base64 = base64.b64encode(json_bytes).decode('utf-8')

        return {
            'type': 'ir.actions.act_url',
            'url': 'data:application/json;base64,' + json_base64,
            'target': 'new',
            'name': 'Descargar JSON',
        }


    def _prepare_invoice_data_payload(self):
        """
        Deprecado: delega a account.move._prepare_invoice_data_for_api (contrato único).
        """
        self.ensure_one()
        invoice = self.account_move_id
        if not invoice:
            raise UserError(_("No associated invoice record found."))
        return invoice._prepare_invoice_data_for_api(invoice)

    def _calculate_tax_summary(self, invoice, processed_lines=None):
        """Retorna tax_summary desde Odoo (``compute_all``). ``processed_lines`` ignorado (compat. legado)."""
        invoice.ensure_one()
        return invoice._prepare_tax_summary_for_dgii_api(invoice)

    def save_and_send_xml(self):
        '''
        Calls the new DGII API endpoint to submit invoice using certificate-based authentication.
        Builds invoice_data from Odoo record, sends to API for XML generation, signing, and DGII submission.
        Returns track_id for async status tracking.
        '''
        cre = self.company_id.fe_dgii_id
        cre = cre.filtered(lambda p: p.active)
        if not cre:
            raise UserError(_('No hay ambiente activo configurado en esta compañia.'))

        # Validate certificate credentials are configured
        if not cre.certificate_file:
            raise UserError(_('No hay certificado digital configurado. Por favor configure el certificado en la configuración de DGII.'))
        if not cre.certificate_password:
            raise UserError(_('No hay contraseña de certificado configurada. Por favor configure la contraseña en la configuración de DGII.'))
        if not cre.rnc:
            raise UserError(_('No hay RNC configurado. Por favor configure el RNC en la configuración de DGII.'))

        # Get the API URL using the new get_api_endpoint method
        api_url = cre.get_api_endpoint('submit_invoice')

        # Prepare certificate data (base64 encoded)
        certificate_b64 = cre.certificate_file.decode('utf-8') if isinstance(cre.certificate_file, bytes) else cre.certificate_file

        # Tipo e-CF desde la factura (name puede ser TEMP-{id})
        invoice = self.account_move_id
        if not invoice:
            raise UserError(_('No hay factura vinculada a este registro XML.'))
        type_document = invoice.doc_type_E(invoice)

        # Determine document flow (ECF for fiscal documents, RFCE for simplified)
        document_flow = 'ECF'  # Default to ECF
        if type_document in ['E32', 'B02']:  # Consumo / Consumidor final
            document_flow = 'RFCE'

        # Mismo contrato que factura / preview: un solo armador
        invoice_data = self.account_move_id._prepare_invoice_data_for_api(self.account_move_id)

        # API: mode=test → _submit_mock (XSD + tracking TEST-*); mode=prod → DGII real
        api_mode = 'test' if cre.dgii_client_mode == 'test' else 'prod'

        # Prepare payload for new DGII API
        payload = {
            'invoice_data': invoice_data,
            'type_document': type_document,
            'document_flow': document_flow,
            'certificate_b64': certificate_b64,
            'certificate_password': cre.certificate_password,
            'rnc': cre.rnc,
            'environment': cre.dgii_environment or 'TesteCF',
            'mode': api_mode,
            'validate_xsd': cre.dgii_validate_xsd, # Nuevo campo para controlar validación XSD
        }
        _logger.info(
            'DGII submit_invoice: api_mode=%s (itx.fe.dgii dgii_client_mode=%s)',
            api_mode,
            cre.dgii_client_mode,
        )

        try:
            response_data = _post_dgii_json_route(api_url, payload, timeout=30)

            # Store the full response
            self.json_response_sent = json.dumps(response_data)

            # Process result based on new API response format
            if response_data.get('success'):
                self.status = 'sent'
                self.track_id = response_data.get('track_id')
                _logger.info("XML enviado exitosamente a DGII: %s, track_id: %s", self.name, self.track_id)

                # Store signed XML and signature if returned
                if response_data.get('signed_xml'):
                    self.signed_xml = response_data.get('signed_xml')
                if response_data.get('signature'):
                    self.signature = response_data.get('signature')
            else:
                # Detect XSD / validation errors (mock or API)
                validation_errors = response_data.get('validation_errors') or response_data.get('errors')
                message = response_data.get('message') or response_data.get('error')

                is_xsd_error = False
                if validation_errors:
                    is_xsd_error = True
                elif isinstance(message, str) and 'xsd' in message.lower():
                    is_xsd_error = True

                # Build a detailed dgi_err_msg combining message + validation errors
                parts = []
                if message:
                    parts.append(str(message))
                if isinstance(validation_errors, list) and validation_errors:
                    parts.extend(str(e) for e in validation_errors if e)
                elif validation_errors:
                    parts.append(str(validation_errors))

                final_msg = " | ".join(parts) if parts else None

                # Always store full API response for debugging
                try:
                    self.json_response_sent = json.dumps(response_data)
                except Exception:
                    pass

                # Soft-handle XSD/validation failures: record in the itx.xml.data.dgii record
                if is_xsd_error:
                    self.status = 'error'
                    # Mirror DGII rejection semantics in UI
                    self.dgi_status = 'RECHAZADO'
                    self.dgi_err_msg = final_msg or 'XSD validation failed'
                    # Preserve track id if provided by mock
                    if response_data.get('track_id'):
                        self.track_id = response_data.get('track_id')
                    _logger.warning(
                        "XSD/Validation failure stored on record %s: %s",
                        self.id,
                        self.dgi_err_msg,
                    )
                    # Do not raise: let caller (action_post) continue and surface error in record UI
                    return response_data

                # Non-validation error: escalate as UserError (connection/auth/etc.)
                error_msg = final_msg or (
                    f"Error desconocido (status={response_data.get('status')})"
                    if response_data.get('status') else 'Error desconocido'
                )
                _logger.error('Error al enviar XML a DGII: %s', error_msg)
                self.dgi_err_msg = error_msg
                raise UserError(_('Error al enviar a DGII: %s') % error_msg)

        except requests.exceptions.Timeout:
            self.status = 'error'
            _logger.error('Timeout al enviar XML a DGII')
            raise UserError(_('Timeout: La API DGII no respondió en 30 segundos'))
        except requests.exceptions.ConnectionError:
            self.status = 'error'
            _logger.error('Error de conexión con la API DGII en %s', api_url)
            raise UserError(_('Error de conexión: No se pudo conectar a la API DGII en %s') % api_url)
        except requests.exceptions.RequestException as e:
            self.status = 'error'
            _logger.error('Error en la conexión a la API DGII: %s', str(e))
            raise UserError(_('Error en la conexión a la API DGII: %s') % str(e))
        except json.JSONDecodeError as e:
            self.status = 'error'
            _logger.error('Respuesta JSON inválida de la API DGII: %s', str(e))
            raise UserError(_('Respuesta JSON inválida de la API DGII'))
          
    def verify_sent_encf(self):
        '''
        Calls the new DGII API endpoint to check invoice status using track_id
        with certificate-based authentication.
        '''
        if not self.track_id:
            raise UserError(_('No hay track_id disponible. Primero debe enviar el XML a DGII.'))

        cre = self.company_id.fe_dgii_id
        cre = cre.filtered(lambda p: p.active)
        if not cre:
            raise UserError(_('No hay ambiente activo configurado en esta compañia.'))

        # Validate certificate credentials are configured
        if not cre.certificate_file:
            raise UserError(_('No hay certificado digital configurado. Por favor configure el certificado en la configuración de DGII.'))
        if not cre.certificate_password:
            raise UserError(_('No hay contraseña de certificado configurada. Por favor configure la contraseña en la configuración de DGII.'))
        if not cre.rnc:
            raise UserError(_('No hay RNC configurado. Por favor configure el RNC en la configuración de DGII.'))

        # Get the API URL using the new get_api_endpoint method
        api_url = cre.get_api_endpoint('check_status')

        # Prepare certificate data (base64 encoded)
        certificate_b64 = cre.certificate_file.decode('utf-8') if isinstance(cre.certificate_file, bytes) else cre.certificate_file

        # Prepare payload for new DGII API status check
        payload = {
            'track_id': self.track_id,
            'certificate_b64': certificate_b64,
            'certificate_password': cre.certificate_password,
            'rnc': cre.rnc,
            'environment': cre.dgii_environment or 'TesteCF',
        }

        try:
            response_data = _post_dgii_json_route(api_url, payload, timeout=30)

            # Store the full response
            self.json_response = json.dumps(response_data)

            # Check for API errors
            if not response_data.get('success'):
                error_msg = response_data.get('error', 'Error desconocido')
                _logger.error('API returned error: %s', error_msg)
                # Don't mark as error - might be still processing
                raise UserError(_('Error al verificar estado: %s') % error_msg)

            # Process status from new API response (prod + mock unified contract)
            status = response_data.get('status')
            status_u = str(status or '').strip().upper()
            dgii_u = str(response_data.get('dgii_status') or '').strip().upper()
            # Mock check_status: success, status=CHECKED, dgii_status=AUTORIZADO|EN_PROCESO|RECHAZADO
            is_approved = status_u == 'APPROVED' or (
                status_u == 'CHECKED' and dgii_u in ('AUTORIZADO', 'PROCESSED')
            )
            is_rejected = status_u == 'REJECTED' or (
                status_u == 'CHECKED' and dgii_u == 'RECHAZADO'
            )
            is_pending = status_u == 'PENDING' or (
                status_u == 'CHECKED' and dgii_u in ('EN_PROCESO', 'EN PROCESO')
            )

            if is_approved:
                self.status = 'procesed'
                _logger.info("XML aprobado por DGII: %s, track_id: %s", self.name, self.track_id)

                auth_num = response_data.get('authorization_number') or response_data.get(
                    'auth_number'
                )
                self.dgii_auth_number = auth_num or self.dgii_auth_number
                self.authorized = True
                self.auth_number = auth_num if auth_num else (self.auth_number or '')
                self.cufe = response_data.get('cufe', self.cufe)

                if response_data.get('signed_xml'):
                    self.signed_xml = response_data.get('signed_xml')
                if response_data.get('signature'):
                    self.signature = response_data.get('signature')

                auth_date_top = response_data.get('auth_date')
                if auth_date_top:
                    try:
                        self.auth_date = fields.Date.to_date(auth_date_top)
                    except (ValueError, TypeError):
                        try:
                            self.auth_date = fields.Date.from_string(str(auth_date_top)[:10])
                        except (ValueError, TypeError):
                            _logger.warning(
                                "Could not parse auth_date from verify response: %s",
                                auth_date_top,
                            )

                result_data = response_data.get('result') or {}
                if result_data:
                    self.cufe = result_data.get('cufe', self.cufe)
                    self.doc_type = result_data.get('docType', self.doc_type)
                    self.doc_date = result_data.get('docDate', self.doc_date)
                    self.company_ruc = result_data.get('companyRuc', self.company_ruc)
                    self.branch_cod = result_data.get('branchCod', self.branch_cod)
                    self.pos_cod = result_data.get('posCod', self.pos_cod)
                    self.fe_number = result_data.get('feNumber', self.fe_number)
                    ad = result_data.get('authDate', self.auth_date)
                    if ad:
                        try:
                            self.auth_date = fields.Date.to_date(ad)
                        except (ValueError, TypeError):
                            pass
                    self.pdf = result_data.get('pdf', self.pdf)
                    self.xml = result_data.get('xml', self.xml)
                    self.date_rec = result_data.get('dateRec', self.date_rec)
                    self.qr_code = result_data.get('qrCode', self.qr_code)
                    self.qr_l1 = result_data.get('qrL1', self.qr_l1)
                    self.qr_l2 = result_data.get('qrL2', self.qr_l2)
                    self.xml_dgii = result_data.get('xmlDGII', self.xml_dgii)
                    self.sub_total = result_data.get('subTotal', self.sub_total)
                    self.tax_total = result_data.get('taxTotal', self.tax_total)
                    self.total = result_data.get('total', self.total)

                self.dgi_status = 'APROBADO'

                if self.account_move_id and self.account_move_id.is_ecf_invoice and self.account_move_id.journal_id.is_dgii:
                    invoice_updates = {}

                    if self.signature:
                        invoice_updates['l10n_do_ecf_security_code'] = self.signature
                    elif result_data and result_data.get('qrL1'):
                        security_code = result_data.get('qrL1').split(': ', 1)[1] if ': ' in result_data.get('qrL1') else result_data.get('qrL1')
                        invoice_updates['l10n_do_ecf_security_code'] = security_code

                    if result_data and result_data.get('qrL2'):
                        try:
                            date_str = result_data.get('qrL2').split(': ', 1)[1] if ': ' in result_data.get('qrL2') else result_data.get('qrL2')
                            sign_date = datetime.strptime(date_str, '%d-%m-%Y %H:%M:%S')
                            invoice_updates['l10n_do_ecf_sign_date'] = sign_date
                        except (ValueError, TypeError, IndexError):
                            _logger.warning("Could not parse sign date: %s", result_data.get('qrL2'))

                    if invoice_updates:
                        self.account_move_id.write(invoice_updates)
                        _logger.info("Updated invoice %s with verification data: %s", self.account_move_id.id, invoice_updates)

            elif is_rejected:
                self.status = 'error'
                self.dgi_status = 'RECHAZADO'
                err_parts = [
                    response_data.get('error_message'),
                    response_data.get('rejection_reason'),
                    response_data.get('error'),
                ]
                ve = response_data.get('validation_errors')
                if isinstance(ve, list) and ve:
                    err_parts.extend(str(x) for x in ve)
                self.dgi_err_msg = ' | '.join(p for p in err_parts if p) or _(
                    'Documento rechazado por DGII'
                )
                _logger.error(
                    "XML rechazado por DGII: %s, track_id: %s, error: %s",
                    self.name,
                    self.track_id,
                    self.dgi_err_msg,
                )

            elif is_pending:
                _logger.info("XML aún en procesamiento en DGII: %s, track_id: %s", self.name, self.track_id)
                self.dgi_status = 'EN PROCESO'

            else:
                _logger.warning(
                    "Estado desconocido de DGII: status=%s dgii_status=%s track_id=%s",
                    status,
                    response_data.get('dgii_status'),
                    self.track_id,
                )

        except requests.exceptions.Timeout:
            _logger.error('Timeout al verificar estado en DGII')
            raise UserError(_('Timeout: La API DGII no respondió en 30 segundos'))
        except requests.exceptions.ConnectionError:
            _logger.error('Error de conexión con la API DGII en %s', api_url)
            raise UserError(_('Error de conexión: No se pudo conectar a la API DGII en %s') % api_url)
        except requests.exceptions.RequestException as e:
            _logger.error('Error en la conexión a la API DGII: %s', str(e))
            raise UserError(_('Error en la conexión a la API DGII: %s') % str(e))
        except json.JSONDecodeError as e:
            _logger.error('Respuesta JSON inválida de la API DGII: %s', str(e))
            raise UserError(_('Respuesta JSON inválida de la API DGII'))

    def action_resend_xml(self):
        # Lógica para reenviar el XML

        self.save_and_send_xml()

    def action_verify_sent_encf(self):
        # Lógica para reenviar el XML
        self.verify_sent_encf()

    def rebuild_xml_to_send(self):
        # TODO: Define the URL of the dgii_api server. This could be a system parameter.
        # For now, assuming it's running on the same server for testing.
        # Replace with the actual URL when deploying on a separate server.
        
        # Get the API URL from system parameters or use default
        api_base_url = self.env['ir.config_parameter'].sudo().get_param('dgii_api.base_url', 'http://localhost:8069')
        api_url = f'{api_base_url.rstrip("/")}/dgii/v1/generate_xml'

        # Gather data from the current record and related records
        invoice = self.account_move_id
        if not invoice:
            raise UserError("No associated invoice record found.")

        # Process invoice lines with additional tax and product information
        processed_lines = []
        for line in invoice.invoice_line_ids:
            line_data = {
                'name': line.name,
                'price_unit': line.price_unit,
                'quantity': line.quantity,
                'discount': line.discount,
                'price_subtotal': line.price_subtotal,
                'price_total': line.price_total,
                'product_id': {
                    'id': line.product_id.id if line.product_id else False,
                    'name': line.product_id.name if line.product_id else '',
                    'default_code': line.product_id.default_code if line.product_id else '',
                },
                'currency_id': {
                    'id': line.currency_id.id,
                    'name': line.currency_id.name,
                    'decimal_places': line.currency_id.decimal_places,
                },
                'tax_ids': []
            }
            
            # Process tax information for each line
            for tax in line.tax_ids:
                tax_data = {
                    'id': tax.id,
                    'name': tax.name,
                    'amount': tax.amount,
                    'price_include': tax.price_include,
                    'tax_scope': getattr(tax, 'tax_scope', ''),
                    'tipo_impuesto_dgii': getattr(tax, 'tipo_impuesto_dgii', None),  # AGREGAR
                }
                line_data['tax_ids'].append(tax_data)
            
            processed_lines.append(line_data)

        # Helper function to safely get and format date fields
        def safe_date_format(date_obj):
            if date_obj:
                if isinstance(date_obj, (datetime, date)):
                    return date_obj.strftime('%Y-%m-%d')
                return str(date_obj)
            return False

        # Safely get NCF expiration date from invoice or journal
        ncf_expiration_date = getattr(invoice, 'ncf_expiration_date', None) or getattr(invoice.journal_id, 'l10n_do_ncf_expiration_date', None)

        # Construct the invoice_data dictionary for the API in the expected nested format
        invoice_data_payload = {
            'record': {
                'invoice_date': safe_date_format(invoice.invoice_date),
                'l10n_latam_document_number': invoice.l10n_latam_document_number or '',
                'ncf_expiration_date': safe_date_format(ncf_expiration_date),
                'partner_id': {
                    'name': invoice.partner_id.name or '',
                    'vat': invoice.partner_id.vat or '',
                    'street': invoice.partner_id.street or '',
                    'state_name': invoice.partner_id.state_id.name if invoice.partner_id.state_id else '',
                    'country_name': invoice.partner_id.country_id.name if invoice.partner_id.country_id else '',
                    'email': invoice.partner_id.email or '',
                },
                'currency_id': {
                    'id': invoice.currency_id.id,
                    'name': invoice.currency_id.name,
                    'decimal_places': invoice.currency_id.decimal_places,
                    'inverse_rate': invoice.currency_id.inverse_rate,
                },
                'company_id': {
                    'fe_dgii_id': self._serialize_datetime_data(invoice.company_id.fe_dgii_id.read()) if invoice.company_id.fe_dgii_id else [],
                },
                'invoice_payments_widget': self._serialize_datetime_data(invoice.invoice_payments_widget),
                'payment_ids': self._serialize_datetime_data(invoice.payment_ids.read()) if invoice.payment_ids else [],
                'l10n_do_origin_ncf': invoice.l10n_do_origin_ncf,
                'debit_origin_id': invoice.debit_origin_id.id if invoice.debit_origin_id else False,
                'withholded_itbis': getattr(invoice, 'withholded_itbis', 0.0),
                'income_withholding': getattr(invoice, 'income_withholding', 0.0),
                'aditional_info_invoice_header1': getattr(invoice, 'aditional_info_invoice_header1', ''),
                'aditional_info_invoice_header2': getattr(invoice, 'aditional_info_invoice_header2', ''),
            },
            'lines': processed_lines,  # Use processed lines with tax information
            'origin_document_data': False,
            'current_user_login_data': False,
        }

        type_document = invoice.doc_type_E(invoice)

        # Prepare the payload for the API request in JSON-RPC format
        # Apply datetime serialization to the entire payload to ensure no datetime objects remain
        payload = {
            'jsonrpc': '2.0',
            'method': 'call',
            'params': {
                'invoice_data': self._serialize_datetime_data(invoice_data_payload),
                'type_document': type_document,
            },
            'id': self.id or 1,
        }

        # Set proper headers
        headers = {
            'Content-Type': 'application/json',
        }

        try:
            # Make the POST request to the dgii_api
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            # Process the API response (which is also in JSON-RPC format)
            response_jsonrpc = response.json()

            # Check for JSON-RPC errors first
            if 'error' in response_jsonrpc:
                error_details = response_jsonrpc['error']
                _logger.error('API returned JSON-RPC error: %s', error_details)
                raise UserError(_('API Error: %s') % error_details.get('message', 'Unknown JSON-RPC error'))

            # Process successful result
            response_data = response_jsonrpc.get('result')

            if not response_data:
                _logger.error('No result data in API response: %s', response_jsonrpc)
                raise UserError(_('No result data received from XML generation API'))

            if response_data.get('xml_content'):
                self.xml_data = response_data['xml_content']
                _logger.info("XML generated successfully by dgii_api for record: %s", self.name)
                
                # Optionally store the filename if provided
                if response_data.get('xml_name'):
                    # You could add a field to store the filename if needed
                    pass
                    
            elif response_data.get('error'):
                # Handle API-level errors (not JSON-RPC errors)
                error_message = response_data['error']
                _logger.error('Error generating XML via dgii_api: %s', error_message)
                raise UserError(_('Error generating XML: %s') % error_message)
            else:
                _logger.error('Unexpected API response format: %s', response_data)
                raise UserError(_('Unexpected response format from XML generation API'))

        except requests.exceptions.Timeout:
            _logger.error('Timeout communicating with dgii_api')
            raise UserError(_('Timeout error: XML generation API did not respond within 30 seconds'))
        except requests.exceptions.ConnectionError:
            _logger.error('Connection error communicating with dgii_api at %s', api_url)
            raise UserError(_('Connection error: Could not connect to XML generation API at %s') % api_url)
        except requests.exceptions.RequestException as e:
            _logger.error('Error communicating with dgii_api: %s', str(e))
            raise UserError(_('Error communicating with XML generation API: %s') % str(e))
        except json.JSONDecodeError as e:
            _logger.error('Invalid JSON response from dgii_api: %s', str(e))
            raise UserError(_('Invalid JSON response from XML generation API'))
        except Exception as e:
            _logger.error('An unexpected error occurred during XML generation API call: %s', str(e))
            raise UserError(_('An unexpected error occurred during XML generation: %s') % str(e))

    def test_api_connection(self):
        """Test API connectivity by calling the test endpoint."""
        api_base_url = self.env['ir.config_parameter'].sudo().get_param('dgii_api.base_url', 'http://localhost:8069')
        api_url = f'{api_base_url}/test'
        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            return {"success": True, "message": "Conexión API OK"}
        except requests.ConnectionError:
            return {"success": False, "error": "Error de conexión al API (proxy/red)"}
        except requests.Timeout:
            return {"success": False, "error": "Timeout al conectar con API"}
        except requests.HTTPError as e:
            return {"success": False, "error": f"Error HTTP API: {e}"}
        except Exception as e:
            return {"success": False, "error": f"Error inesperado: {e}"}

    def doc_type_E(self,doc_string):
        # Verificamos que el string tenga el formato esperado
        if len(doc_string) >= 13:  # E + 10 dígitos
            # Extraemos el segundo y tercer carácter (índices 1 y 2)
            result = doc_string[1:3]  # Esto devuelve los caracteres en los índices 1 y 2
            return result
        return "FF"
