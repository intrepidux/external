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


class AccountMove(models.Model):
    _inherit = 'account.move'
    _description = 'Herencia para editar el post de la factura webpos'

    # Mapeo actualizado para 2026
    E_CF_VENTAS = ["31", "32", "44", "45", "46"]
    E_CF_COMPRAS = ["41", "43", "47"]
    E_CF_AJUSTES = ["33", "34"]

    _API_DOCUMENT_TYPE_MAP = {
        # Electronic Document Types (e-NCF)
        "E31": "FF",
        "E32": "FC",
        "E33": "D",
        "E34": "C",
        "E41": "P",
        "E43": "E",
        "E44": "FE",
        "E45": "FG",
        "E46": "FX",
        "E47": "PY",
        # Códigos numéricos
        "31": "FF",
        "32": "FC",
        "33": "D",
        "34": "C",
        "41": "P",
        "43": "E",
        "44": "FE",
        "45": "FG",
        "46": "FX",
        "47": "PY",
        # Códigos alfanuméricos
        "FF": "FF",
        "FC": "FC",
        "D": "D",
        "C": "C",
        "P": "P",
        "E": "E",
        "FE": "FE",
        "FG": "FG",
        "FX": "FX",
        "PY": "PY",
        # Fallbacks
        "out_invoice": "FF",
        "out_refund": "C",
        "out_debit": "D",
        "in_invoice": "P",
    }




    # pos_order_ids = fields.One2many('pos.order', 'account_move')
    # pos_payment_ids = fields.One2many('pos.payment', 'account_move_id')
 
    xml_data = fields.Text('XML Data')
    xml_data_ids = fields.One2many('my.xml.data', 'account_move_id', string='XML Data ids') #pendiente eliminar


    xml_data_id = fields.Many2one('my.xml.data', string='My XML Data')

    l10n_do_itbis_tax_group_id = fields.Many2one(
        'account.tax.group',
        string='ITBIS Tax Group',
        compute='_compute_l10n_do_itbis_tax_group_id'
    )

    def _compute_l10n_do_itbis_tax_group_id(self):
        itbis_group = self.env.ref('l10n_do.tax_group_itbis', raise_if_not_found=False)
        for record in self:
            record.l10n_do_itbis_tax_group_id = itbis_group

    # campos de my.xml.data mapeo
    # Los campos serán accesibles a través de my_xml_data_id
    xml_name = fields.Char(related='xml_data_id.name', string='Name XML', store=True)
    xml_data = fields.Text(related='xml_data_id.xml_data', string='XML Data', store=True)
    status = fields.Selection(related='xml_data_id.status', string='WebPosStatus', store=True)
    dgi_status = fields.Char(related='xml_data_id.dgi_status', string='Estado DGII', store=True)
    dgi_err_msg = fields.Text(related='xml_data_id.dgi_err_msg', string='Error Message', store=True)
    # json_response = fields.Text(related='xml_data_id.json_response', string='Json Response')  # Descomentar si es necesario

    # Campos para facturación electrónica WebPOS
    l10n_do_ecf_security_code = fields.Char(string="e-CF Security Code", copy=False)
    l10n_do_ecf_sign_date = fields.Datetime(string="e-CF Sign Date", copy=False)

    # Campo para sello electrónico QR WebPOS (related para consistencia)
    l10n_do_webpos_electronic_stamp = fields.Char(
        related='xml_data_id.qr_code',
        string="WebPOS Electronic Stamp",
        store=True,
        help="Sello electrónico QR obtenido del API WebPOS (evita conflicto con espaillatcomercial)"
    )



    # Campo computado para determinar si es factura electrónica (compatible con ambas versiones)
    is_ecf_invoice = fields.Boolean(
        string="Is Electronic Invoice",
        compute="_compute_is_ecf_invoice",
        store=False,  # No almacenar para compatibilidad
        help="Computed field to determine if invoice is electronic (e-NCF) based on document type"
    )

    #fin mapeo campos my.xml.data



    def _compute_is_ecf_invoice(self):
        """Compute is_ecf_invoice based on document type (compatible with both versions)"""
        for record in self:
            # Check if l10n_latam_document_type_id exists and has doc_code_prefix
            if (hasattr(record, 'l10n_latam_document_type_id') and
                record.l10n_latam_document_type_id and
                hasattr(record, 'l10n_latam_document_type_id') and
                record.l10n_latam_document_type_id and
                hasattr(record.l10n_latam_document_type_id, 'doc_code_prefix')):
                # If document type code starts with 'E', it's an electronic invoice
                record.is_ecf_invoice = record.l10n_latam_document_type_id.doc_code_prefix and record.l10n_latam_document_type_id.doc_code_prefix.startswith('E')
            else:
                # Fallback: if we can't determine from document type, check company settings
                # This maintains compatibility with the original Adel logic
                record.is_ecf_invoice = (
                    hasattr(record.company_id, 'l10n_do_ecf_issuer') and
                    record.company_id.l10n_do_ecf_issuer and
                    record.country_code == "DO"
                )

    def get_clean_description(self, line):
        """Obtiene descripción limpia del producto truncada a 80 caracteres para DGII.

        Prioriza el nombre base del producto (product_template_id.name) para evitar
        códigos adicionales como 'P00204:' o '[05116.001.150]' que Odoo agrega en line.name.
        """
        # Obtener nombre base del producto (sin variantes)
        if line.product_id and line.product_id.product_template_id:
            description = line.product_id.product_template_id.name
        else:
            description = line.name or ''

        # Truncar a 80 caracteres si excede
        if len(description) > 80:
            description = description[:77] + '...'

        return description

    def _get_webpos_ecf_modification_code(self, invoice):
        """
        Calculate automatically the e-CF modification code for WebPOS API.

        WebPOS API only accepts codes 1 and 3:
        - "1" = Total Cancellation (when credit note amount == original invoice amount)
        - "3" = Amount correction (when credit note amount < original invoice amount)

        This method works independently of any localization field.
        """
        # Only apply to credit notes (out_refund) and debit notes (out_debit)
        if invoice.move_type not in ('out_refund', 'out_debit'):
            return ''

        # Get the original invoice
        original_invoice = None
        if invoice.move_type == 'out_refund' and invoice.reversed_entry_id:
            original_invoice = invoice.reversed_entry_id
        elif invoice.move_type == 'out_debit' and invoice.debit_origin_id:
            original_invoice = invoice.debit_origin_id

        if not original_invoice:
            _logger.warning(f"Cannot determine modification code: no original invoice found for {invoice.name}")
            return ''

        # Compare amounts using absolute values (to handle negative amounts in refunds)
        current_amount = abs(invoice.amount_total)
        original_amount = abs(original_invoice.amount_total)

        # Use a small epsilon for float comparison
        epsilon = 0.01

        if abs(current_amount - original_amount) < epsilon:
            # Total cancellation - amounts are equal
            return '1'
        else:
            # Amount correction - credit note is for less than original
            return '3'

    def _validate_webpos_invoice(self):
        """Valida todos los requisitos de WebPOS antes de confirmar la factura.

        Recoge todos los errores y los muestra juntos al final.
        Solo aplica para diarios WebPOS.
        """
        if not self.journal_id.is_webpos:
            return

        errors = []

        # 1. Validar RNC/Cédula para facturas >= 250,000
        if self.amount_total >= 250000:
            if not self.partner_id.vat or not self.partner_id.vat.strip():
                errors.append(
                    _("- Cliente sin RNC/Cédula: Para facturas >= RD$250,000 es obligatorio.")
                )

        # 2. Validar que cada línea tenga al menos un impuesto
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
            if not line.tax_ids:
                errors.append(
                    _("- Línea '%s' no tiene impuestos configurados. "
                      "Cada línea debe tener al menos un impuesto (ej: ITBIS 18 o exento).") 
                    % line.name[:50]
                )

        # 3. Validar impuestos verificados
        taxes = self.line_ids.tax_ids
        unverified_taxes = taxes.filtered(lambda t: not t.itx_tax_verified)
        if unverified_taxes:
            tax_names = ", ".join(unverified_taxes.mapped("name"))
            errors.append(
                _("- Impuestos sin verificar: %s") % tax_names
            )

        # Lanzar error conjunto si hay errores
        if errors:
            raise UserError(
                _("La factura no puede ser confirmada. Por favor, corrija los siguientes errores:\n\n%s")
                % "\n".join(errors)
            )

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


    def _is_l10n_do_webpos_allowed_document(self):
        self.ensure_one()
        # Si no es factura electrónica o no tiene número de documento o no es diario webpos, no está permitida
        if not self.is_ecf_invoice or not self.l10n_latam_document_number or not self.journal_id.is_webpos:
            return False

        # Extraer el tipo (ej. '31' de 'E310000000005')
        # El tipo son los dos dígitos después de la 'E'
        tipo_ecf = self.l10n_latam_document_number[1:3]
        flujo = "ventas" if self.move_type.startswith("out_") else "compras"

        if flujo == "ventas":
            # Ventas directas + Notas de crédito/débito que afecten ventas
            return tipo_ecf in self.E_CF_VENTAS or tipo_ecf in self.E_CF_AJUSTES
        elif flujo == "compras":
            # Compras (remitidas en 606) + Notas que afecten gastos
            return tipo_ecf in self.E_CF_COMPRAS or tipo_ecf in self.E_CF_AJUSTES
        return False

    def action_post(self):
        # Validar antes de confirmar (solo para WebPOS)
        self._validate_webpos_invoice()

        res = super(AccountMove, self).action_post()

        invoices = self.env['account.move'].browse(self.ids)
        


        # Lógica adicional después de confirmar la factura

        for invoice in invoices:
            _logger.info("=" * 50)
            _logger.info("=" * 50)
            _logger.error("invoice_id: %s, is_ecf:%s, is_webpos: %s, latam_document: %s", invoice,invoice.is_ecf_invoice, invoice.journal_id.is_webpos, invoice.l10n_latam_document_number) 
            _logger.info("=" * 50)
            _logger.info("=" * 50)

            if invoice._is_l10n_do_webpos_allowed_document():

                    doc_type = self.doc_type_E(invoice)
                    xml_content, xml_name = self.build_xml_to_print(invoice, doc_type)
                    xml_data = xml_content
                    try:
                        execute_EF = invoice.create_xml_data(invoice, xml_data)
                        if invoice.amount_total >= 250000:
                            if not invoice.partner_id.vat or not invoice.partner_id.vat.strip():
                                raise UserError(
                                    _(
                                        "Para facturas con monto total igual o mayor a RD$250,000, es obligatorio que el cliente tenga RNC o Cédula registrado."
                                    )
                                )
                        taxes = self.line_ids.tax_ids
                        unverified_taxes = taxes.filtered(lambda t: not t.itx_tax_verified)
                        if unverified_taxes:
                            raise UserError(
                                _(
                                    "Los siguientes impuestos no están verificados para WebPOS: %s"
                                )
                                % ", ".join(unverified_taxes.mapped("name"))
                            )
                        execute_EF.save_and_send_xml()
                        execute_EF.verify_sent_encf()
                        if invoice.l10n_latam_document_number.startswith("TEMP-"):
                            document_number = (
                                invoice.l10n_do_fiscal_sequence_id.get_fiscal_number()
                            )
                            invoice.write(
                                {
                                    "l10n_latam_document_number": document_number,
                                    "payment_reference": f"{invoice.name} - {document_number}",
                                }
                            )
                            if invoice.xml_data_id:
                                invoice.xml_data_id.name = document_number
                    except Exception as e:
                        raise UserError(
                            _("Error al crear el documento Electronico: %s" % str(e))
                        )
                    self.xml_print_to_std(xml_content)
            else:
                _logger.info(
                    "WebPOS API call skipped for invoice %s: Document type %s not allowed for current flow.",
                    invoice.id,
                    invoice.l10n_latam_document_number[1:3]
                    
                )


        return res



    def print_invoice(self):
        
               
        invoice = self.env['account.move'].browse(self.id)


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
                    tax_data = {
                        'name': tax.name or '',
                        'amount': tax.amount or 0.0,
                        'price_include': tax.price_include or False,
                        'tax_group_id': tax.tax_group_id.id if tax.tax_group_id else False
                    }
                    # Map tipo_impuesto_webpos exclusively for ITBIS taxes (group "ITBIS" and positive amount)
                    if tax.tax_group_id.name == 'ITBIS' and tax.amount > 0:
                        tax_data['tipo_impuesto_webpos_itbis'] = tax.tipo_impuesto_webpos
                    line_taxes.append(tax_data)

                # Adjust price_unit for exclusive pricing if taxes are inclusive
                adjusted_price_unit = line.price_unit or 0.0
                if line_taxes and any(tax.get('price_include', False) for tax in line_taxes):
                    # Compute exclusive price_unit from inclusive price
                    # For simplicity, assume single inclusive tax per line
                    inclusive_tax = next((tax for tax in line_taxes if tax.get('price_include', False)), None)
                    if inclusive_tax:
                        tax_rate = inclusive_tax.get('amount', 0.0) / 100.0
                        # Formula: exclusive_price = inclusive_price / (1 + tax_rate)
                        adjusted_price_unit = line.price_unit / (1 + tax_rate) if tax_rate > 0 else line.price_unit



                lines_data.append({
                    'name': self.get_clean_description(line),
                    'quantity': line.quantity or 0.0,
                    'price_unit': adjusted_price_unit,
                    'price_subtotal': line.price_subtotal or 0.0,
                    'price_total': line.price_total or 0.0,
                    'tax_ids': line_taxes,
                    'product_id': {
                        'name': line.product_id.name or '',
                        'default_code': line.product_id.default_code or False
                    }
                })

            # Determine NCF expiration date with robust handling for all invoice types
            ncf_expiration_date = ''
            original_invoice = None

            # For credit/debit notes, get the expiration date from the original invoice
            if invoice.move_type == 'out_refund' and invoice.reversed_entry_id:
                original_invoice = invoice.reversed_entry_id
            elif invoice.move_type == 'out_debit' and invoice.debit_origin_id:
                original_invoice = invoice.debit_origin_id

            # Try to get expiration date from original invoice first (for credit/debit notes)
            if original_invoice:
                if hasattr(original_invoice, 'l10n_do_ncf_expiration_date') and original_invoice.l10n_do_ncf_expiration_date:
                    try:
                        ncf_expiration_date = original_invoice.l10n_do_ncf_expiration_date.strftime('%Y-%m-%d')
                    except (AttributeError, ValueError, TypeError):
                        ncf_expiration_date = ''
                elif hasattr(original_invoice, 'ncf_expiration_date') and original_invoice.ncf_expiration_date:
                    try:
                        ncf_expiration_date = original_invoice.ncf_expiration_date.strftime('%Y-%m-%d')
                    except (AttributeError, ValueError, TypeError):
                        ncf_expiration_date = ''

            # If no expiration date from original invoice, or for regular invoices, get from current invoice
            if not ncf_expiration_date:
                if hasattr(invoice, 'l10n_do_ncf_expiration_date') and invoice.l10n_do_ncf_expiration_date:
                    try:
                        ncf_expiration_date = invoice.l10n_do_ncf_expiration_date.strftime('%Y-%m-%d')
                    except (AttributeError, ValueError, TypeError):
                        ncf_expiration_date = ''
                elif hasattr(invoice, 'ncf_expiration_date') and invoice.ncf_expiration_date:
                    try:
                        ncf_expiration_date = invoice.ncf_expiration_date.strftime('%Y-%m-%d')
                    except (AttributeError, ValueError, TypeError):
                        ncf_expiration_date = ''
                # Additional fallback: try to get from journal
                elif hasattr(invoice.journal_id, 'l10n_do_ncf_expiration_date') and invoice.journal_id.l10n_do_ncf_expiration_date:
                    try:
                        ncf_expiration_date = invoice.journal_id.l10n_do_ncf_expiration_date.strftime('%Y-%m-%d')
                    except (AttributeError, ValueError, TypeError):
                        ncf_expiration_date = ''

            # Calculate e-CF modification code automatically for WebPOS
            ecf_modification_code = self._get_webpos_ecf_modification_code(invoice)
            _logger.info("DEBUG: l10n_do_ecf_modification_code being sent to API: %s", ecf_modification_code)

            # Determine origin NCF and reference date for credit/debit notes
            # Debug logging for l10n_do_origin_ncf field
            _logger.error(f"DEBUG: invoice.l10n_do_origin_ncf raw value: {getattr(invoice, 'l10n_do_origin_ncf', 'FIELD_NOT_FOUND')}")
            _logger.error(f"DEBUG: invoice.l10n_do_origin_ncf type: {type(getattr(invoice, 'l10n_do_origin_ncf', None))}")

            l10n_do_origin_ncf = getattr(invoice, 'l10n_do_origin_ncf', None) or ''
            # Ensure it's a string
            if not isinstance(l10n_do_origin_ncf, str):
                l10n_do_origin_ncf = str(l10n_do_origin_ncf) if l10n_do_origin_ncf is not None else ''

            # Compute l10n_do_origin_ncf_date by searching for the origin invoice
            l10n_do_origin_ncf_date = ''
            if l10n_do_origin_ncf:
                credit_origin_id = self.env["account.move"].sudo().search(
                    [("l10n_latam_document_number", "=", l10n_do_origin_ncf)], limit=1
                )
                if credit_origin_id:
                    # Use the date of the found origin invoice
                    l10n_do_origin_ncf_date = credit_origin_id.invoice_date.strftime('%Y-%m-%d') if credit_origin_id.invoice_date else ''
                else:
                    l10n_do_origin_ncf_date = ''
            else:
                l10n_do_origin_ncf_date = ''

            # Prepare main invoice record data
            record_data = {
                'invoice_date': invoice.invoice_date.strftime('%Y-%m-%d') if invoice.invoice_date else '',
                'l10n_latam_document_number': invoice.l10n_latam_document_number or '',
                'ncf_expiration_date': ncf_expiration_date,
                'l10n_do_origin_ncf': l10n_do_origin_ncf,
                'l10n_do_origin_ncf_date': l10n_do_origin_ncf_date,
                'l10n_do_income_type': invoice.l10n_do_income_type,
                'l10n_do_ecf_modification_code': ecf_modification_code,
                'partner_id': partner_data,
                'currency_id': currency_data,
                'company_id': company_data,
                'invoice_payments_widget': getattr(invoice, 'invoice_payments_widget', None),
                'payment_ids': [],  # Add payment data if needed
                'reversed_entry_id': invoice.reversed_entry_id.id if invoice.reversed_entry_id else None,
                'debit_origin_id': invoice.debit_origin_id.id if invoice.debit_origin_id else None,
                'lines': lines_data,
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
            _logger.info("Fiscal Number: %s", invoice.l10n_latam_document_number)
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
            
            response = self._call_webpos_api('/generate_xml', api_data)
            
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

    def action_manual_resend_webpos(self):
        """
        Manual action to resend WebPOS documents that were not processed initially.
        This method performs the complete WebPOS sending process:
        1. Validates invoice eligibility
        2. Creates XML data if it doesn't exist
        3. Sends XML to WebPOS API
        4. Verifies the sent document
        """
        self.ensure_one()

        # Validate invoice eligibility for WebPOS
        if not (self.is_ecf_invoice and self.journal_id.is_webpos and self.l10n_latam_document_number and self.journal_id.l10n_latam_use_documents):
            raise UserError(_('Esta factura no es elegible para envío WebPOS. Debe ser una factura electrónica en un diario WebPOS con número fiscal válido.'))

        # Check document type validation using the new unified method
        if not self._is_l10n_do_webpos_allowed_document():
            raise UserError(
                _(
                    "El tipo de documento %s (%s) no está permitido en el diario %s para el flujo de %s."
                )
                % (
                    self.l10n_latam_document_type_id.name,
                    self.l10n_latam_document_number[1:3]
                    if self.l10n_latam_document_number
                    else "N/A",
                    self.journal_id.name,
                    "ventas" if self.move_type.startswith("out_") else "compras",
                )
            )

        try:
            # Create XML data if it doesn't exist
            if not self.xml_data_id:
                _logger.info("Creating XML data for manual WebPOS resend of invoice %s", self.id)
                doc_type = self.doc_type_E(self)
                xml_content, xml_name = self.build_xml_to_print(self, doc_type)

                xml_data = self.env['my.xml.data'].create({
                    'name': self.l10n_latam_document_number,
                    'xml_data': xml_content,
                    'account_move_id': self.id,
                    'status': 'pending',
                })
                self.xml_data_id = xml_data.id
            else:
                _logger.info("Using existing XML data for manual WebPOS resend of invoice %s", self.id)

            # Send XML to WebPOS
            _logger.info("Sending XML to WebPOS for invoice %s", self.id)
            self.xml_data_id.save_and_send_xml()

            # Verify sent document
            _logger.info("Verifying sent document for invoice %s", self.id)
            self.xml_data_id.verify_sent_encf()

            # Log success
            _logger.info("Manual WebPOS resend completed successfully for invoice %s", self.id)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Éxito'),
                    'message': _('Documento reenviado exitosamente a WebPOS.'),
                    'type': 'success',
                }
            }

        except Exception as e:
            _logger.error("Error in manual WebPOS resend for invoice %s: %s", self.id, str(e))
            raise UserError(_('Error al reenviar documento a WebPOS: %s') % str(e))


    # fin mapeo funciones heredadas de xml_data_id


## REVISAR constraints para evitar duplicado de impuestos en la lineas de factura

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    _description = 'Herencia para validar impuestos únicos por grupo en líneas de WebPOS'

    @api.constrains('tax_ids')
    def _check_single_tax_per_group_webpos(self):
        """Ensure only one tax per tax_group_id is applied to invoice lines for WebPOS."""
        for line in self:
            # Only validate for WebPOS journals and when invoice is posted or being posted
            if (line.tax_ids and line.move_id and line.move_id.journal_id.is_webpos and
                line.move_id.state in ['posted', 'draft'] and line.display_type == 'product'):
                # Group taxes by tax_group_id
                tax_groups = {}
                for tax in line.tax_ids:
                    if tax.tax_group_id:
                        group_id = tax.tax_group_id.id
                        if group_id not in tax_groups:
                            tax_groups[group_id] = []
                        tax_groups[group_id].append(tax.name)

                # Check for duplicates in any group
                duplicate_groups = []
                for group_id, tax_names in tax_groups.items():
                    if len(tax_names) > 1:
                        group_name = line.tax_ids.filtered(lambda t: t.tax_group_id.id == group_id)[0].tax_group_id.name
                        duplicate_groups.append((group_name, tax_names))

                if duplicate_groups:
                    error_messages = []
                    for group_name, tax_names in duplicate_groups:
                        error_messages.append(
                            _("Grupo '%s': %s") % (group_name, ', '.join(tax_names))
                        )
                    raise models.ValidationError(
                        _("No puede haber más de un impuesto del mismo grupo por línea en facturas WebPOS:\n%s") %
                        '\n'.join(error_messages)
                    )

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
