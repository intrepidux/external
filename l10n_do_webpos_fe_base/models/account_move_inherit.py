# Part of Odoo. See LICENSE file for full copyright and licensing details.

import io
import os
import requests
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

import datetime
# from odoo.addons.l10n_do_webpos_fe_base.utils.xml_base import XmlInterface # Old import, removed as logic moved to webpos_api


class AccountMove(models.Model):
    _inherit = 'account.move'
    _description = 'Herencia para editar el post de la factura webpos'

    # Mapping of Odoo NCF types/move types to WebPOS API document types
    # This combines both the short codes and the numeric codes for clarity
    # Updated based on actual example XML files from Ejemplos_api_webpos folder
    _API_DOCUMENT_TYPE_MAP = {
        # Fiscal Document Types (Official DGII B Series) - Aligned with E series
        'B01': 'FF', # Comprobante de Crédito Fiscal (B01) -> FF (same as E31)
        'B02': 'FC', # Comprobante para Consumidor Final (B02) -> FC (same as E32)
        'B03': 'D', # Comprobante de Débito (B03) -> DD (same as E33)
        'B04': 'C', # Comprobante de Crédito (B04) -> CC (same as E34)
        
        # Special Comprobantes (Official DGII B Series) - Aligned with E series
        'B11': 'P',   # Comprobante de Compras (B11) -> P (same as E41)
        'B12': 'RUI', # Comprobante de Registro Único de Ingresos (B12) -> RUI (unique, no E equivalent)
        'B13': 'E',   # Comprobante para Gastos Menores (B13) -> E (same as E43)
        'B14': 'FE',  # Comprobante para Regímenes Especiales (B14) -> FE (same as E44)
        'B15': 'FG',  # Comprobante Gubernamental (B15) -> FG (same as E45)
        'B16': 'FX',  # Comprobante para Exportaciones (B16) -> FX (same as E46)
        'B17': 'PY',  # Comprobante para Pagos al Exterior (B17) -> PY (same as E47)

        # Electronic Document Types (e-NCF) - Updated based on example XML files
        'E31': 'FF', # Factura de Crédito Fiscal Electrónica -> FF (confirmed)
        'E32': 'FC', # Factura de Consumo Electrónica -> FC (confirmed)
        'E33': 'D',  # Nota de Débito Electrónica 
        'E34': 'C',  # Nota de Crédito Electrónica
        'E41': 'P',  # Comprobante de Compras Electrónico -> P (confirmed)
        'E43': 'E',  # Gastos Menores Electrónico -> E (updated from 'FE')
        'E44': 'FE', # Regímenes Especiales Electrónico -> FE (updated from 'PY')
        'E45': 'FG', # Gubernamental Electrónico -> FG (updated from 'FX')
        'E46': 'FX', # Factura de Exportación Electrónica -> FX (updated from 'E')
        'E47': 'PY', # Pagos al Exterior Electrónico -> PY (updated from 'FG')

        # Numeric codes mapped to alphanumeric for API compatibility - Updated
        '31': 'FF',
        '32': 'FC',
        '33': 'D', 
        '34': 'C',
        '41': 'P',
        '43': 'E',  # Updated to match E43
        '44': 'FE', # Updated to match E44
        '45': 'FG', # Updated to match E45
        '46': 'FX', # Updated to match E46
        '47': 'PY', # Updated to match E47

        # Standalone alphanumeric codes (for direct API compatibility) - Updated
        'FF': 'FF',
        'FC': 'FC',
        'D': 'D',  
        'C': 'C', 
        'P': 'P',
        'E': 'E',
        'FE': 'FE',
        'FG': 'FG',
        'FX': 'FX',
        'PY': 'PY',

        # Odoo Move Types fallback (for cases where NCF might not be set yet or is generic)
        'out_invoice': 'FF', # Default for sales invoices (assume fiscal unless specified by NCF)
        'out_refund': 'C',  # Default for credit notes 
        'out_debit': 'D',   # Default for debit notes 
        'in_invoice': 'P',   # Default for purchase invoices (though typically no e-CF for these)
    }




    # pos_order_ids = fields.One2many('pos.order', 'account_move')
    # pos_payment_ids = fields.One2many('pos.payment', 'account_move_id')
 
    xml_data = fields.Text('XML Data')
    xml_data_ids = fields.One2many('my.xml.data', 'account_move_id', string='XML Data ids') #pendiente eliminar


    xml_data_id = fields.Many2one('my.xml.data', string='My XML Data')

    # campos de my.xml.data mapeo
    # Los campos serán accesibles a través de my_xml_data_id
    xml_name = fields.Char(related='xml_data_id.name', string='Name XML', store=True)
    xml_data = fields.Text(related='xml_data_id.xml_data', string='XML Data', store=True)
    status = fields.Selection(related='xml_data_id.status', string='WebPosStatus', store=True)
    dgi_status = fields.Char(related='xml_data_id.dgi_status', string='Estado DGII', store=True)
    dgi_err_msg = fields.Text(related='xml_data_id.dgi_err_msg', string='Error Message', store=True)
    # json_response = fields.Text(related='xml_data_id.json_response', string='Json Response')  # Descomentar si es necesario
    
    #fin mapeo campos my.xml.data

    def _get_api_base_url(self):
        """Get the API base URL from system parameters"""
        return self.env['ir.config_parameter'].sudo().get_param('webpos_api.base_url', 'http://localhost:8069')

    def _call_webpos_api(self, endpoint, data):
        """Make a JSON-RPC call to the webpos_api endpoints"""
        try:
            base_url = self._get_api_base_url()
            url = f"{base_url}{endpoint}"
            
            # Prepare JSON-RPC format
            jsonrpc_data = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": data,
                "id": 1
            }
            
            headers = {
                'Content-Type': 'application/json',
            }
            
            _logger.info(f"Making API call to: {url}")
            _logger.info(f"JSON-RPC Data: {json.dumps(jsonrpc_data, indent=2)}")
            
            response = requests.post(url, json=jsonrpc_data, headers=headers, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            _logger.error(f"API call to {endpoint} failed: {str(e)}")
            raise UserError(_('Error calling WebPOS API: %s') % str(e))
        except Exception as e:
            _logger.error(f"Unexpected error calling API {endpoint}: {str(e)}")
            raise UserError(_('Unexpected error calling WebPOS API: %s') % str(e))

    def copy(self, default=None):
        # Asegúrate de que 'default' sea un diccionario para evitar errores
        if default is None:
            default = {}

        # Elimina la relación xml_data_id al duplicar
        default['xml_data_id'] = False  # Mantiene vacío al duplicar

        # Llama al método original para duplicar el registro
        return super(AccountMove, self).copy(default=default)


    @api.model
    def create_xml_data(self, invoice, xml_content):
        # Crear un nuevo registro en my.xml.data
        xml_data = self.env['my.xml.data'].create({
            'name': invoice.l10n_latam_document_number,
            'xml_data': xml_content, 
            'account_move_id': invoice.id,  # Asocia el XML con la factura
            'status': 'pending',  # Establece el estado inicial
        })

        # Asigna el registro creado a xml_data_id en account.move
        invoice.xml_data_id = xml_data.id 

        return xml_data


    def action_post(self):
        # Llamar al método original
        res = super(AccountMove, self).action_post()
        invoice = self.env['account.move'].browse(self.id)
        _logger.error("<-- print_invoice  action_post()--> %s", invoice) 


        # Lógica adicional después de confirmar la factura
     
        for invoice in self:
            _logger.error("<-- print_invoice antes de 108-->")
            _logger.error(f"Debug condition: invoice.is_ecf_invoice = {invoice.is_ecf_invoice}")
            _logger.error(f"Debug condition: invoice.journal_id.is_webpos = {invoice.journal_id.is_webpos}")
            _logger.error(f"Debug condition: not invoice.l10n_do_fiscal_number = {not invoice.l10n_do_fiscal_number}")
            _logger.error(f"Debug value : invoice.l10n_do_fiscal_number = {invoice.l10n_do_fiscal_number}")
            _logger.error(f"Debug condition: Full condition result = {(invoice.is_ecf_invoice and invoice.journal_id.is_webpos) and (invoice.l10n_do_fiscal_number)}")
            if (invoice.is_ecf_invoice and invoice.journal_id.is_webpos) and (invoice.l10n_do_fiscal_number and invoice.journal_id.l10n_latam_use_documents):
                _logger.error("<-- print_invoice despues de 1108 IF -->")
                if invoice.move_type in ('out_invoice', 'in_invoice', 'out_refund', 'out_debit'):
                    doc_type = self.doc_type_E(invoice) # Pass the invoice object
                    xml_content, xml_name = self.build_xml_to_print(invoice, doc_type)
                    xml_data = xml_content  # Generar el XML

                    

                
                    # # Es factura de compras y  no se genera documentos electronico ( venta proveedor)
                    # if (invoice.move_type in 'in_invoice') and self.doc_type_E(self.l10n_latam_document_number) in ("31","32"):
                    #     # Es factura de compras y  no se genera documentos electronico ( venta proveedor)
                    #     # Crear el documento EDI
                    #     _logger.error("<-- NO GENERA comprobante -->")
                    # else:
                    try:
                    # Llama al método con el contenido XML
                    
                        execute_EF = invoice.create_xml_data(invoice, xml_data)
                        
                        #Activar envio diferido, apaga envio automatico  para envaluar documentos antes de ser enviados
                        execute_EF.save_and_send_xml()
                        execute_EF.verify_sent_encf()

                    except Exception as e:
                        raise UserError(_('Error al crear el documento Electronico: %s' % str(e)))
                        
                    # Print XML to standard output using the new API approach
                    self.xml_print_to_std(xml_content)
                

        return res



    def print_invoice(self):
        
               
        invoice = self.env['account.move'].browse(self.id)
        _logger.error("<-- print_invoice 888-->")
        _logger.error("<-- print_invoice 888-->")
        _logger.error("<-- print_invoice 888-->")
        _logger.error("<-- print_invoice 888-->")

        # _logger.error("<-- print_invoice --> %s", invoice) 

        # Determine document type based on invoice characteristics
        doc_type = self.doc_type_E(invoice)
            
        xml_content, xml_name = self.build_xml_to_print(invoice, doc_type)
            
                
        xml = self.xml_print_to_std(xml_content)        
        _logger.error("<-- XML 123-->")
        _logger.error(xml)
              
            

        return invoice




    def _get_invoiced_lot_values(self):
        self.ensure_one()

        lot_values = super(AccountMove, self)._get_invoiced_lot_values()
        # _logger.error("<-- accountInvoice --> IT IS Error 2")
    
        inv = self.env['account.move'].browse(self.id)
        # inv = inv()    
        #_logger.error("<--factura--> %s ", inv)
        _logger.error('<--factura nombre--> {0}'.format(inv))
        # No longer needed: _logger.error("<-- prefijo 347 --> %s ", self._prefijo_factura) 

        
        #xml_name = "<--xml name--> "
        try:
            #xml_name = XmlInterface.build_xml_to_print2(inv)
            
            # Determine document type based on invoice characteristics
            doc_type = self.doc_type_E(inv)
            xml_content, xml_name = self.build_xml_to_print(inv, doc_type)
            
            _logger.error("<--1 generando xml 7777--> ")
            # Create a new instance of the MyXMLData model
            my_data = self.env['my.xml.data'].create({
                'name': xml_name,
                'xml_data': xml_content,
                
            })
            #my_data.generate_and_save_xml()

            # Generate and save the XML data
            # No longer needed: # ### my_data.save_and_send_xml(host='25.64.242.10', username='demo', password='demo',port='22', remote_directory='/')

    

            _logger.error("<--1 se imprimio--> ")
        except IndexError as e:
            _logger.error("<-- index error  %s--> ", e)
        except AssertionError as e:
            _logger.error("<-- assertion error  %s--> ", e)
        except AttributeError as e:
            _logger.error("<-- attribute error  %s--> ", e)
        except ImportError as e:
            _logger.error("<-- ImportError  %s--> ", e)
        except KeyError as e:
            _logger.error("<-- KeyError  %s--> ", e)
        except NameError as e:
            _logger.error("<-- NameError  %s--> ", e)
        except MemoryError as e:
            _logger.error("<-- MemoryError  %s--> ", e)
        except TypeError as e:
            _logger.error("<-- TypeError  %s--> ", e)

        else:
            try:
                # self.xml_print_to_std(xml_content)
                self.xml_print_to_std("xml_content")
            except IndexError as e:
                _logger.error("<-- index error2  %s--> ", e)
            except AssertionError as e:
                _logger.error("<-- assertion error2  %s--> ", e)
            except AttributeError as e:
                _logger.error("<-- attribute error2  %s--> ", e)
            except ImportError as e:
                _logger.error("<-- ImportError2  %s--> ", e)
            except KeyError as e:
                _logger.error("<-- KeyError2  %s--> ", e)
            except NameError as e:
                _logger.error("<-- NameError2  %s--> ", e)
            except MemoryError as e:
                _logger.error("<-- MemoryError2  %s--> ", e)
            except TypeError as e:
                _logger.error("<-- TypeError2  %s--> ", e)
        
        return lot_values

    def _get_reconciled_vals(self, partial, amount, counterpart_line):
        """Add pos_payment_name field in the reconciled vals to be able to show the payment method in the invoice."""
        result = super()._get_reconciled_vals(partial, amount, counterpart_line)
        # _logger.error("<-- accountInvoice --> IT IS Error 3")

        return result

    #def _get_name_invoice_report(self):
    #    """ This method need to be inherit by the localizations if they want to print a custom invoice report instead of
    #    the default one. For example please review the l10n_ar module """
            
            
            
    #    inv = super()._get_name_invoice_report(self.id)  
    #    _logger.error("<-- accountInvoice --> IT IS Error 4")
    #t    return inv

    def _prepare_invoice_data_for_api(self, invoice):
        """Prepare comprehensive invoice data for API with robust error handling"""
        try:
            # Prepare partner data with comprehensive fallback
            partner_data = {
                'name': invoice.partner_id.name or '',
                'vat': invoice.partner_id.vat or '',
                'street': invoice.partner_id.street or '',
                'state_name': invoice.partner_id.state_id.name if invoice.partner_id.state_id else '',
                'country_name': invoice.partner_id.country_id.name if invoice.partner_id.country_id else '',
                'email': invoice.partner_id.email or ''
            }

            # Prepare currency data
            currency_data = {
                'id': invoice.currency_id.id,
                'name': invoice.currency_id.name or '',
                'decimal_places': invoice.currency_id.decimal_places or 2,
                'inverse_rate': invoice.currency_id.rate or 1.0
            }

            # Prepare company data with fallback
            company_data = {}
            if hasattr(invoice.company_id, 'fe_webpos_id') and invoice.company_id.fe_webpos_id:
                company_data['fe_webpos_id'] = [{
                    'name': invoice.company_id.name or 'TEST',
                    'companyLicCod': invoice.company_id.fe_webpos_id[0].companyLicCod if invoice.company_id.fe_webpos_id else 'UNKNOWN',
                    'branchCod': invoice.company_id.fe_webpos_id[0].branchCod if invoice.company_id.fe_webpos_id else '001',
                    'posCod': invoice.company_id.fe_webpos_id[0].posCod if invoice.company_id.fe_webpos_id else '001'
                }]

            # Prepare invoice lines data
            lines_data = []
            for line in invoice.invoice_line_ids:
                line_taxes = []
                for tax in line.tax_ids:
                    line_taxes.append({
                        'name': tax.name or '',
                        'amount': tax.amount or 0.0
                    })

                lines_data.append({
                    'name': line.name or '',
                    'quantity': line.quantity or 0.0,
                    'price_unit': line.price_unit or 0.0,
                    'price_subtotal': line.price_subtotal or 0.0,
                    'price_total': line.price_total or 0.0,
                    'tax_ids': line_taxes,
                    'product_id': {
                        'name': line.product_id.name or '',
                        'default_code': line.product_id.default_code or False
                    }
                })

            # Determine NCF expiration date with fallback
            ncf_expiration_date = ''
            if hasattr(invoice, 'l10n_do_ncf_expiration_date') and invoice.l10n_do_ncf_expiration_date:
                ncf_expiration_date = invoice.l10n_do_ncf_expiration_date.strftime('%Y-%m-%d')
            elif hasattr(invoice, 'ncf_expiration_date') and invoice.ncf_expiration_date:
                ncf_expiration_date = invoice.ncf_expiration_date.strftime('%Y-%m-%d')

            # Prepare main invoice record data
            record_data = {
                'invoice_date': invoice.invoice_date.strftime('%Y-%m-%d') if invoice.invoice_date else '',
                'l10n_latam_document_number': invoice.l10n_latam_document_number or '',
                'ncf_expiration_date': ncf_expiration_date,
                'partner_id': partner_data,
                'currency_id': currency_data,
                'company_id': company_data,
                'invoice_payments_widget': getattr(invoice, 'invoice_payments_widget', None),
                'payment_ids': [],  # Add payment data if needed
                'reversed_entry_id': invoice.reversed_entry_id.id if invoice.reversed_entry_id else None,
                'debit_origin_id': invoice.debit_origin_id.id if invoice.debit_origin_id else None,
                'lines': lines_data,
                'withholded_itbis': getattr(invoice, 'withholded_itbis', 0.0),
                'income_withholding': getattr(invoice, 'income_withholding', 0.0),
                'aditional_info_invoice_header1': getattr(invoice, 'aditional_info_invoice_header1', ''),
                'aditional_info_invoice_header2': getattr(invoice, 'aditional_info_invoice_header2', ''),
            }

            def clean_dates(obj):
                if isinstance(obj, dict):
                    return {k: clean_dates(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean_dates(i) for i in obj]
                elif isinstance(obj, (datetime.date, datetime.datetime)):
                    return obj.isoformat()
                return obj

            # Limpia fechas antes de serializar
            record_data_clean = clean_dates(record_data)
            lines_data_clean = clean_dates(lines_data)
            _logger.error("API DATA: %s", json.dumps(record_data_clean, indent=2))
            return {
                'record': record_data_clean,
                'lines': lines_data_clean,
            }

        except Exception as e:
            _logger.error(f"Error preparing invoice data for API: {str(e)}")
            raise UserError(_('Error preparing invoice data: %s') % str(e))

    def build_xml_to_print(self, invoice, type_document):
        """Generate XML using the webpos_api endpoint with comprehensive logging"""
        try:
            # Prepare invoice data for the API
            _logger.info("Starting XML generation for invoice %s", invoice.id)
            
            # Log detailed invoice information for debugging
            _logger.info("Invoice Details:")
            _logger.info("Move Type: %s", invoice.move_type)
            _logger.info("Document Number: %s", invoice.l10n_latam_document_number)
            _logger.info("Company: %s", invoice.company_id.name)
            _logger.info("Partner: %s", invoice.partner_id.name)
            
            # Log invoice conditions
            _logger.info("Invoice Conditions:")
            _logger.info("Is ECF Invoice: %s", invoice.is_ecf_invoice)
            _logger.info("Journal is WebPOS: %s", invoice.journal_id.is_webpos)
            _logger.info("Fiscal Number: %s", invoice.l10n_do_fiscal_number)
            _logger.info("Journal Uses Documents: %s", invoice.journal_id.l10n_latam_use_documents)
            
            # Prepare invoice data for the API
            
            invoice_data = self._prepare_invoice_data_for_api(invoice)
            
            # Log the prepared invoice data for debugging
            _logger.info("Prepared Invoice Data:")
            _logger.info(json.dumps(invoice_data, indent=2))
            
            # Validate invoice data before API call
            if not invoice_data or not invoice_data.get('record'):
                _logger.error("Invalid invoice data: Empty or missing record")
                raise UserError(_('Invalid invoice data. Cannot generate XML.'))
            
            # Call the webpos_api generate_xml endpoint
            api_data = {
                'invoice_data': invoice_data,
                'type_document': type_document
            }
            
            _logger.info("Calling WebPOS API with type_document: %s", type_document)
            _logger.info("API Request Data: %s", json.dumps(api_data, indent=2))
            
            response = self._call_webpos_api('/webpos_api/generate_xml', api_data)
            
            # Log the full API response
            _logger.info("WebPOS API Response:")
            _logger.info(json.dumps(response, indent=2))
            
            # Check for errors in the response
            if 'error' in response:
                _logger.error("XML Generation API Error: %s", response['error'])
                raise UserError(_('XML Generation Error: %s') % response['error'])
            
            # Extract XML content
            xml_content = response.get('result', {}).get('xml_content', '')
            xml_name = response.get('result', {}).get('xml_name', f'{type_document}_{invoice.l10n_latam_document_number}.xml')
            
            # Additional validation of XML content
            if not xml_content:
                _logger.error("No XML content generated for invoice %s", invoice.id)
                _logger.error("Full API Response: %s", json.dumps(response, indent=2))
                raise UserError(_('No XML data was generated for the invoice. Please check the invoice details and API configuration.'))
            
            _logger.info("XML Generation Successful. XML Name: %s", xml_name)
            _logger.info("XML Content Length: %d characters", len(xml_content))
            
            return xml_content, xml_name
            
        except Exception as e:
            # Comprehensive error logging
            _logger.error("Detailed Error in build_xml_to_print:")
            _logger.error("Error Type: %s", type(e).__name__)
            _logger.error("Error Message: %s", str(e))
            
            # Log traceback for more detailed debugging
            import traceback
            _logger.error("Full Traceback:\n%s", traceback.format_exc())
            
            # Raise a user-friendly error with context
            raise UserError(_(
                'Error generating XML for invoice %s:\n'
                'Type: %s\n'
                'Details: %s\n'
                'Please check invoice details, API configuration, and system logs.'
            ) % (invoice.id, type(e).__name__, str(e)))
    
    def xml_print_to_std(self, content):
        """Print XML content to standard output (logging)"""
        try:
            _logger.info("=== XML CONTENT START ===")
            _logger.info(content)
            _logger.info("=== XML CONTENT END ===")
            return content
        except Exception as e:
            _logger.error(f"Error printing XML to std: {str(e)}")
        return content
    
    def xml_print_to_file(self, content, file_name, invoice): 
        """Save XML content to file (placeholder implementation)"""
        try:
            # This is a placeholder implementation
            # In a real scenario, you might want to save to a specific directory
            _logger.info(f"Would save XML to file: {file_name}")
            _logger.info(f"XML content length: {len(content) if content else 0}")
            return file_name
        except Exception as e:
            _logger.error(f"Error in xml_print_to_file: {str(e)}")
            return file_name

    def doc_type_E(self, invoice):
        """
        Determines the appropriate WebPOS API document type (FF, FC, D, C, etc.)
        based on the invoice's NCF or move type.
        
        NOTE: This module is primarily designed to work with 'Serie E' electronic invoices (e-NCFs).
        While it handles other NCF types for mapping purposes, the main focus is on e-invoices.
        """
        import re
        doc_type = None

        # 1. Prioritize NCF type from l10n_latam_document_number
        if invoice.l10n_latam_document_number:
            _logger.info(f"EX347 0 Latam Document {invoice.l10n_latam_document_number}")
            # Try to match the full NCF type (e.g., 'E31', 'B02')
            ncf_match = re.match(r'^(E\d{2}|B\d{2})', invoice.l10n_latam_document_number)
            if ncf_match:
                ncf_prefix = ncf_match.group(1)
                _logger.info(f"EX347 1 Prefix ncf {ncf_prefix}")
                doc_type = self._API_DOCUMENT_TYPE_MAP.get(ncf_prefix)
                _logger.info(f"EX347 2 Prefix ncf mapped {ncf_prefix}")
                if doc_type:
                    _logger.info(f"Resolved document type from NCF prefix {ncf_prefix}: {doc_type}")
                    return doc_type

            # Fallback for short alphanumeric codes if they appear at the beginning of the number
            short_code_match = re.match(r'^(FF|FC|D|C|P|E|FE|FG|FX|PY)', invoice.l10n_latam_document_number)
            if short_code_match:
                short_code = short_code_match.group(1)
                doc_type = self._API_DOCUMENT_TYPE_MAP.get(short_code)
                if doc_type:
                    _logger.info(f"Resolved document type from short NCF code {short_code}: {doc_type}")
                    return doc_type
            
            # Fallback for numeric codes if they appear at the beginning of the number
            numeric_code_match = re.match(r'^(\d{2})', invoice.l10n_latam_document_number)
            if numeric_code_match:
                numeric_code = numeric_code_match.group(1)
                doc_type = self._API_DOCUMENT_TYPE_MAP.get(numeric_code)
                if doc_type:
                    _logger.info(f"Resolved document type from numeric code {numeric_code}: {doc_type}")
                    return doc_type

        # 2. Fallback to move_type and debit/credit note origin
        if invoice.move_type:
            # Custom logic for debit notes (out_invoice with debit_origin_id)
            if invoice.move_type == 'out_invoice' and invoice.debit_origin_id:
                doc_type = self._API_DOCUMENT_TYPE_MAP.get('out_debit')
            else:
                doc_type = self._API_DOCUMENT_TYPE_MAP.get(invoice.move_type)

            if doc_type:
                _logger.info(f"Resolved document type from move_type {invoice.move_type}: {doc_type}")
                return doc_type

        # 3. Default if no specific type is found
        _logger.warning(f"Could not determine specific document type for invoice {invoice.id} (NCF: {invoice.l10n_latam_document_number}, Name: {invoice.name}, Move Type: {invoice.move_type}). Defaulting to FF.")
        return 'FF' # Default to Fiscal Invoice (FF) if nothing else matches

    # funciones heredadas de xml_data_id
    def action_resend_xml(self):
        self.xml_data_id.action_resend_xml()

    def rebuild_xml_to_send(self):
        # Verifica si existe un registro de my.xml.data asociado
        if not self.xml_data_id:
            # Si no existe, crea un nuevo registro en my.xml.data
            # Determine document type based on current invoice characteristics
            doc_type = self.doc_type_E(self) # Pass the invoice object
            _logger_.info("EX444 0 doctype rebuild {doc_type}")
            xml_content, xml_name = self.build_xml_to_print(self, doc_type)  # Genera el contenido XML
            xml_data = self.env['my.xml.data'].create({
                'name': self.l10n_latam_document_number,  # O el campo que desees usar
                'xml_data': xml_content,
                'account_move_id': self.id,  # Asocia el XML con la factura
                'status': 'pending',  # Establece el estado inicial
            })
            self.xml_data_id = xml_data.id  # Asigna el nuevo registro al campo xml_data_id
        
        self.xml_data_id.rebuild_xml_to_send()

    def action_verify_sent_encf(self):
        self.xml_data_id.action_verify_sent_encf()
    # fin mapeo funciones heredadas de xml_data_id
    

    # @api.constrains("state", "line_ids", "l10n_latam_document_type_id")
    # def _check_special_exempt(self):
    #     """ Validates that an invoice with a Special Tax Payer type does not contain
    #         nor ITBIS or ISC.
    #         See DGII Norma 05-19, Art 3 for further information.
    #     """
    #     for rec in self.filtered(
    #         lambda r: r.company_id.country_id == self.env.ref("base.do")
    #         and r.l10n_latam_document_type_id
    #         and r.move_type == "out_invoice"
    #         and r.state in ("posted")
    #     ):


    #         if rec.l10n_latam_document_type_id.l10n_do_ncf_type == "special":
    #             # If any invoice tax in ITBIS or ISC
    #             taxes = ("ITBIS", "ISC")
    #             if any(
    #                 [
    #                     tax
    #                     for tax in rec.line_ids.filtered("tax_line_id").filtered(
    #                         lambda tax: tax.tax_group_id.name in taxes
    #                         and tax.tax_base_amount != 0
    #                     )
    #                 ]
    #             ):
    #                 raise UserError(
    #                     _(
    #                         "You cannot validate and invoice of Fiscal Type "
    #                         "Regímen Especial with ITBIS/ISC.\n\n"
    #                         "See DGII General Norm 05-19, Art. 3 for further "
    #                         "information"
    #                     )
    #                 )
