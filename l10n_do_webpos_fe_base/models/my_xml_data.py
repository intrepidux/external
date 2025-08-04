from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import requests
import logging
import base64
import json
from datetime import datetime, date
#from odoo.addons.l10n_do_webpos_fe_base.utils.xml_base import XmlInterface

_logger = logging.getLogger(__name__)

class MyXMLData(models.Model):
    _name = 'my.xml.data'
    _description = 'Maneja el procesamiento de documento XML '
    
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
    account_move_id = fields.Many2one('account.move', string='Cuenta de Movimiento')
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

    # Campos de webpos.document response api
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
    xml_webpos = fields.Text(string="XML WebPOS")
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
    #         record = super(MyXMLData, self).create(vals)
            
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


    def save_and_send_xml(self):
        ''' 
        Refactored: Calls the webpos_api endpoint to send XML and updates the record with the response.
        '''
        cre = self.company_id.fe_webpos_id     
        cre = cre.filtered(lambda p: p.active)
        if not cre:
            raise UserError(_('No hay ambiente activo configurado en esta compañia.'))
         
        api_credentials = {
            'url_base': cre.url_base,
            'name': cre.name,
            'companyLicCod': cre.companyLicCod,
            'apk': cre.apk,
        }
        xml_content = self.xml_data if self.xml_data else ""
        if not xml_content:
            raise UserError(_('No hay datos XML para enviar.'))

        # Get the API URL from system parameters or use default
        api_base_url = self.env['ir.config_parameter'].sudo().get_param('webpos_api.base_url', 'http://localhost:8069')
        api_url = f'{api_base_url}/webpos_api/send_xml'
        
        # Prepare payload in JSON-RPC format
        payload = {
            'jsonrpc': '2.0',
            'method': 'call',
            'params': {
                'xml_content': xml_content,
                'api_credentials': api_credentials,
            },
            'id': self.id or 1,
        }
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            response_jsonrpc = response.json()
            
            # Check for JSON-RPC errors
            if 'error' in response_jsonrpc:
                error_details = response_jsonrpc['error']
                _logger.error('API returned JSON-RPC error: %s', error_details)
                self.status = 'error'
                raise UserError(_('API Error: %s') % error_details.get('message', 'Unknown JSON-RPC error'))
            
            # Process result
            response_data = response_jsonrpc.get('result', {})
            
            # Update record based on response
            if response_data.get('received') == True and response_data.get('accepted') == True:
                self.status = 'sent'
                _logger.info("XML enviado exitosamente: %s", self.name)
                self.json_response_sent = json.dumps(response_data)
            else:
                self.status = 'error'
                self.json_response_sent = json.dumps(response_data)
                _logger.error('Error al enviar XML: %s', response_data)
                self.dgi_err_msg = response_data.get("dgiErrMsg")
                
        except requests.exceptions.Timeout:
            self.status = 'error'
            _logger.error('Timeout al enviar XML')
            raise UserError(_('Timeout: La API no respondió en 30 segundos'))
        except requests.exceptions.ConnectionError:
            self.status = 'error'
            _logger.error('Error de conexión con la API en %s', api_url)
            raise UserError(_('Error de conexión: No se pudo conectar a la API en %s') % api_url)
        except requests.exceptions.RequestException as e:
            self.status = 'error'
            _logger.error('Error en la conexión a la API: %s', str(e))
            raise UserError(_('Error en la conexión a la API: %s') % str(e))
        except json.JSONDecodeError as e:
            self.status = 'error'
            _logger.error('Respuesta JSON inválida de la API: %s', str(e))
            raise UserError(_('Respuesta JSON inválida de la API'))
          
    def verify_sent_encf(self):
        ''' 
        Refactored: Calls the webpos_api endpoint to verify document status and updates the record with the response.
        '''
        document_number = self.account_move_id.l10n_latam_document_number
        if not document_number:
            raise UserError("El número de documento no está definido.")
        cre = self.company_id.fe_webpos_id     
        cre = cre.filtered(lambda p: p.active)
        if not cre:
            raise UserError(_('No hay ambiente activo configurado en esta compañia.'))
            
        api_credentials = {
            'url_base': cre.url_base,
            'name': cre.name,
            'companyLicCod': cre.companyLicCod,
            'apk': cre.apk,
        }
        
        # Get the API URL from system parameters or use default
        api_base_url = self.env['ir.config_parameter'].sudo().get_param('webpos_api.base_url', 'http://localhost:8069')
        api_url = f'{api_base_url}/webpos_api/verify_status'
        
        # Prepare payload in JSON-RPC format
        payload = {
            'jsonrpc': '2.0',
            'method': 'call',
            'params': {
                'api_credentials': api_credentials,
                'document_number': document_number,
                'cufe': self.cufe or '',
            },
            'id': self.id or 1,
        }
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            response_jsonrpc = response.json()
            
            # Check for JSON-RPC errors
            if 'error' in response_jsonrpc:
                error_details = response_jsonrpc['error']
                _logger.error('API returned JSON-RPC error: %s', error_details)
                self.status = 'error'
                raise UserError(_('API Error: %s') % error_details.get('message', 'Unknown JSON-RPC error'))
            
            # Process result
            response_data = response_jsonrpc.get('result')
            
            if response_data:
                self.status = 'procesed'
                _logger.info("XML verificado exitosamente: %s", self.name)
                self.json_response = json.dumps(response_data)
                # Update fields from response
                self.cufe = response_data.get('cufe')
                self.doc_type = response_data.get('docType')
                self.doc_date = response_data.get('docDate')
                self.company_lic_cod = response_data.get('companyLicCod')
                self.company_ruc = response_data.get('companyRuc')
                self.branch_cod = response_data.get('branchCod')
                self.pos_cod = response_data.get('posCod')
                self.fe_number = response_data.get('feNumber')
                self.authorized = response_data.get('authorized')
                self.auth_number = response_data.get('authNumber')
                self.auth_date = response_data.get('authDate')
                self.pdf = response_data.get('pdf')
                self.xml = response_data.get('xml')
                self.date_rec = response_data.get('dateRec')
                self.system_ref = response_data.get('system_ref')
                self.doc_affected_ref = response_data.get('docAffectedRef')
                self.sub_doc_type = response_data.get('subDocType')
                self.qr_code = response_data.get('qrCode')
                self.qr_l1 = response_data.get('qrL1')
                self.qr_l2 = response_data.get('qrL2')
                self.xml_webpos = response_data.get('xmlWebPOS')
                self.sub_total = response_data.get('subTotal')
                self.tax_total = response_data.get('taxTotal')
                self.total = response_data.get('total')
                self.sbt0 = response_data.get('sbt0')
                self.sbt1 = response_data.get('sbt1')
                self.sbt2 = response_data.get('sbt2')
                self.sbt3 = response_data.get('sbt3')
                self.tax1 = response_data.get('tax1')
                self.tax2 = response_data.get('tax2')
                self.tax3 = response_data.get('tax3')
                self.dgi_resp = response_data.get('dgiResp')
                self.dgi_err_msg = response_data.get('dgiErrMsg')
                self.sts = response_data.get('sts')
                self.dgi_sts = response_data.get('dgiSts')
                self.dgi_status = response_data.get('dgiStatus')
            else:
                self.status = 'error'
                self.json_response = json.dumps(response_jsonrpc)
                _logger.error('No se recibieron datos en la respuesta de verificación')
                
        except requests.exceptions.Timeout:
            self.status = 'error'
            _logger.error('Timeout al verificar XML')
            raise UserError(_('Timeout: La API no respondió en 30 segundos'))
        except requests.exceptions.ConnectionError:
            self.status = 'error'
            _logger.error('Error de conexión con la API en %s', api_url)
            raise UserError(_('Error de conexión: No se pudo conectar a la API en %s') % api_url)
        except requests.exceptions.RequestException as e:
            self.status = 'error'
            _logger.error('Error en la conexión a la API: %s', str(e))
            raise UserError(_('Error en la conexión a la API: %s') % str(e))
        except json.JSONDecodeError as e:
            self.status = 'error'
            _logger.error('Respuesta JSON inválida de la API: %s', str(e))
            raise UserError(_('Respuesta JSON inválida de la API'))

    def action_resend_xml(self):
        # Lógica para reenviar el XML

        self.save_and_send_xml()

    def action_verify_sent_encf(self):
        # Lógica para reenviar el XML
        self.verify_sent_encf()

    def rebuild_xml_to_send(self):
        # TODO: Define the URL of the webpos_api server. This could be a system parameter.
        # For now, assuming it's running on the same server for testing.
        # Replace with the actual URL when deploying on a separate server.
        
        # Get the API URL from system parameters or use default
        api_base_url = self.env['ir.config_parameter'].sudo().get_param('webpos_api.base_url', 'http://localhost:8069')
        api_url = f'{api_base_url}/webpos_api/generate_xml'

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
                    'tax_scope': getattr(tax, 'tax_scope', ''),  # Use getattr in case field doesn't exist
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
                    'fe_webpos_id': self._serialize_datetime_data(invoice.company_id.fe_webpos_id.read()) if invoice.company_id.fe_webpos_id else [],
                },
                'invoice_payments_widget': self._serialize_datetime_data(invoice.invoice_payments_widget),
                'payment_ids': self._serialize_datetime_data(invoice.payment_ids.read()) if invoice.payment_ids else [],
                'reversed_entry_id': invoice.reversed_entry_id.id if invoice.reversed_entry_id else False,
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

        # Determine the document type based on the current record (self.name)
        type_document = self.doc_type_E(self.name)

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
            # Make the POST request to the webpos_api
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
                _logger.info("XML generated successfully by webpos_api for record: %s", self.name)
                
                # Optionally store the filename if provided
                if response_data.get('xml_name'):
                    # You could add a field to store the filename if needed
                    pass
                    
            elif response_data.get('error'):
                # Handle API-level errors (not JSON-RPC errors)
                error_message = response_data['error']
                _logger.error('Error generating XML via webpos_api: %s', error_message)
                raise UserError(_('Error generating XML: %s') % error_message)
            else:
                _logger.error('Unexpected API response format: %s', response_data)
                raise UserError(_('Unexpected response format from XML generation API'))

        except requests.exceptions.Timeout:
            _logger.error('Timeout communicating with webpos_api')
            raise UserError(_('Timeout error: XML generation API did not respond within 30 seconds'))
        except requests.exceptions.ConnectionError:
            _logger.error('Connection error communicating with webpos_api at %s', api_url)
            raise UserError(_('Connection error: Could not connect to XML generation API at %s') % api_url)
        except requests.exceptions.RequestException as e:
            _logger.error('Error communicating with webpos_api: %s', str(e))
            raise UserError(_('Error communicating with XML generation API: %s') % str(e))
        except json.JSONDecodeError as e:
            _logger.error('Invalid JSON response from webpos_api: %s', str(e))
            raise UserError(_('Invalid JSON response from XML generation API'))
        except Exception as e:
            _logger.error('An unexpected error occurred during XML generation API call: %s', str(e))
            raise UserError(_('An unexpected error occurred during XML generation: %s') % str(e))

    def doc_type_E(self,doc_string):
        # Verificamos que el string tenga el formato esperado
        if len(doc_string) >= 13:  # E + 10 dígitos
            # Extraemos el segundo y tercer carácter (índices 1 y 2)
            result = doc_string[1:3]  # Esto devuelve los caracteres en los índices 1 y 2
            return result
        return "FF"