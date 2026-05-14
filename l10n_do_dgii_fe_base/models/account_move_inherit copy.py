# Part of Odoo. See LICENSE file for full copyright and licensing details.

import io
import os
import requests
import json
from urllib.parse import quote
from odoo import api, fields, models, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

import datetime


class AccountMove(models.Model):
    _inherit = 'account.move'
    _description = 'Herencia para editar el post de la factura dgii'

    # Mapeo de tipos E-CF para DGII (referencia estándar DGII)
    E_CF_VENTAS = ["31", "32", "44", "45", "46"]
    E_CF_COMPRAS = ["41", "43", "47"]
    E_CF_AJUSTES = ["33", "34"]


    itx_dgii_xml_data_raw = fields.Text('XML Data Raw')
    itx_xml_data_ids = fields.One2many('itx.xml.data.dgii', 'account_move_id', string='XML Data DGII ids')


    itx_xml_data_id = fields.Many2one('itx.xml.data.dgii', string='XML Data DGII', ondelete='set null')

    l10n_do_itbis_tax_group_id = fields.Many2one(
        'account.tax.group',
        string='ITBIS Tax Group',
        compute='_compute_l10n_do_itbis_tax_group_id'
    )

    def _compute_l10n_do_itbis_tax_group_id(self):
        itbis_group = self.env.ref('l10n_do.tax_group_itbis', raise_if_not_found=False)
        for record in self:
            record.l10n_do_itbis_tax_group_id = itbis_group

    # campos de itx.xml.data.dgii mapeo - renombrados con prefijo itx_dgii_ para evitar conflictos
    # Los campos serán accesibles a través de itx_xml_data_id
    itx_dgii_xml_name = fields.Char(related='itx_xml_data_id.name', string='Name XML DGII', store=True)
    itx_dgii_xml_data = fields.Text(related='itx_xml_data_id.xml_data', string='XML Data DGII (Relacionado)', store=True)
    itx_dgii_status = fields.Selection(related='itx_xml_data_id.status', string='DGII Status', store=True)
    itx_dgii_dgi_status = fields.Char(related='itx_xml_data_id.dgi_status', string='Estado DGII (Relacionado)', store=True)
    itx_dgii_dgi_err_msg = fields.Text(related='itx_xml_data_id.dgi_err_msg', string='DGII Error Message', store=True)
    # itx_dgii_json_response = fields.Text(related='itx_xml_data_id.json_response', string='Json Response DGII')  # Descomentar si es necesario

    # Campos para facturación electrónica DGII
    l10n_do_ecf_security_code = fields.Char(string="e-CF Security Code", copy=False)
    l10n_do_ecf_sign_date = fields.Datetime(string="e-CF Sign Date", copy=False)

    # Campo para sello electrónico QR DGII (related para consistencia)
    itx_dgii_electronic_stamp = fields.Char(
        related='itx_xml_data_id.qr_code',
        string="DGII Electronic Stamp",
        store=True,
        help="Sello electrónico QR obtenido del API DGII"
    )


    itx_dgii_electronic_stamp_encoded = fields.Char(
        compute="_compute_qr_encoded"
    )

    @api.depends('itx_dgii_electronic_stamp')
    def _compute_qr_encoded(self):
        for rec in self:
            rec.itx_dgii_electronic_stamp_encoded = quote(rec.itx_dgii_electronic_stamp or '')



    # Campo computado para determinar si es factura electrónica (compatible con ambas versiones)
    is_ecf_invoice = fields.Boolean(
        string="Is Electronic Invoice",
        compute="_compute_is_ecf_invoice",
        store=False,  # No almacenar para compatibilidad
        help="Computed field to determine if invoice is electronic (e-NCF) based on document type"
    )

    #fin mapeo campos itx.xml.data.dgii



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

    def _get_fiscal_rate(self):
        '''
        Ejemplos:
        - Compañía base DOP, factura USD: retorna ~60.0
        - Compañía base USD, factura USD: retorna ~60.0
        - Compañía base DOP, factura DOP: retorna 1.0
        
        '''
        self.ensure_one()
        # 1. Si la factura es en DOP, no hay nada que hacer
        if self.currency_id.name == 'DOP':
            return 1.0
            
        # 2. Optimización: Si la compañía es DOP, el inverse_rate ya es lo que buscamos
        if self.company_id.currency_id.name == 'DOP':
            return  round(self.currency_id.inverse_rate or 1.0, 4)

        # 3. Caso "No hay de otra": La compañía no es DOP, calculamos relación relativa
        currency_dop = self.env.ref('base.DOP', raise_if_not_found=False) or \
                       self.env['res.currency'].search([('name', '=', 'DOP')], limit=1)
        
        if currency_dop and self.currency_id.rate:
            # (Unidades de DOP por 1 unidad base) / (Unidades de moneda factura por 1 unidad base)
            return  round(currency_dop.rate / self.currency_id.rate, 4)
            
        return  round(self.currency_id.inverse_rate or 1.0, 4)

    def get_clean_description(self, line):
        """Obtiene descripción limpia del producto truncada a 80 caracteres para DGII.
        
        Si el usuario modificó manualmente la descripción, la respetamos.
        Si es la descripción automática de Odoo, usamos el nombre del producto 
        para evitar códigos de referencia o formatos internos.
        """
        product = line.product_id
        line_name = line.name or ''
        
        # Solo procesar si la línea es de tipo 'product'
        if line.display_type != 'product':
            return '' # No enviar secciones o notas al API

        if product:
            product_name = product.name or ''
            # Si el nombre del producto está contenido en la línea, 
            # es probable que sea la descripción automática (ej: "[REF] Producto")
            # En ese caso, preferimos el nombre limpio del producto.
            if product_name in line_name:
                description = product_name
            else:
                # Si el usuario cambió la descripción y ya no coincide con el nombre 
                # del producto, respetamos su cambio manual.
                description = line_name
        else:
            description = line_name

        # Truncar a 80 caracteres para cumplimiento DGII
        if len(description) > 80:
            description = description[:77] + '...'

        return description

    def _get_dgii_ecf_modification_code(self, invoice):
        """
        Calculate automatically the e-CF modification code for DGII API.

        DGII API only accepts codes 1 and 3:
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

    def _validate_dgii_invoice(self):
        """Valida todos los requisitos de DGII antes de confirmar la factura.

        Recoge todos los errores y los muestra juntos al final.
        Solo aplica para diarios DGII.
        """
        _logger.info("[VALIDATE %s] START _validate_dgii_invoice", self.name)
        _logger.info("[VALIDATE %s] journal_id=%s, is_dgii=%s", self.name, self.journal_id.id, getattr(self.journal_id, 'is_dgii', 'N/A'))

        if not self.journal_id.is_dgii:
            _logger.info("[VALIDATE %s] SKIPPED: Journal is not DGII", self.name)
            return

        _logger.info("[VALIDATE %s] Journal IS DGII, validating...", self.name)

        errors = []

        # 1. Validar RNC/Cédula para facturas >= 250,000
        _logger.info("[VALIDATE %s] Checking RNC for amount_total=%s", self.name, self.amount_total)
        if self.amount_total >= 250000:
            _logger.info("[VALIDATE %s] Amount >= 250000, checking partner VAT...", self.name)
            if not self.partner_id.vat or not self.partner_id.vat.strip():
                _logger.warning("[VALIDATE %s] ERROR: Missing VAT for partner %s", self.name, self.partner_id.name)
                errors.append(
                    _("- Cliente sin RNC/Cédula: Para facturas >= RD$250,000 es obligatorio.")
                )

        # 2. Validar que cada línea tenga al menos un impuesto
        _logger.info("[VALIDATE %s] Checking taxes on invoice lines...", self.name)
        product_lines = self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        _logger.info("[VALIDATE %s] Found %d product lines", self.name, len(product_lines))

        for line in product_lines:
            _logger.info("[VALIDATE %s] Line '%s': tax_ids=%s", self.name, line.name[:30], line.tax_ids)
            if not line.tax_ids:
                _logger.warning("[VALIDATE %s] ERROR: Line '%s' has no taxes!", self.name, line.name[:30])
                errors.append(
                    _("- Línea '%s' no tiene impuestos configurados. "
                      "Cada línea debe tener al menos un impuesto (ej: ITBIS 18 o exento).")
                    % line.name[:50]
                )

        # 3. Validar impuestos verificados
        _logger.info("[VALIDATE %s] Checking verified taxes...", self.name)
        taxes = self.line_ids.tax_ids
        _logger.info("[VALIDATE %s] All taxes found: %s", self.name, taxes.mapped('name'))

        unverified_taxes = taxes.filtered(lambda t: not t.itx_tax_verified)
        _logger.info("[VALIDATE %s] Unverified taxes: %s", self.name, unverified_taxes.mapped('name'))

        if unverified_taxes:
            tax_names = ", ".join(unverified_taxes.mapped("name"))
            _logger.warning("[VALIDATE %s] ERROR: Unverified taxes: %s", self.name, tax_names)
            errors.append(
                _("- Impuestos sin verificar: %s") % tax_names
            )

        # Lanzar error conjunto si hay errores
        if errors:
            error_msg = "\n".join(errors)
            _logger.error("[VALIDATE %s] VALIDATION FAILED with %d errors:\n%s", self.name, len(errors), error_msg)
            raise UserError(
                _("La factura no puede ser confirmada. Por favor, corrija los siguientes errores:\n\n%s")
                % error_msg
            )

        _logger.info("[VALIDATE %s] PASSED: All validations passed", self.name)

    def _get_api_base_url(self):
        """Get the API base URL from system parameters"""
        return self.env['ir.config_parameter'].sudo().get_param('dgii_api.base_url', 'http://localhost:8069')

    def _call_dgii_api(self, endpoint, data):
        """Make a JSON-RPC call to the dgii_api endpoints"""
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
            raise UserError(_('Error calling DGII API: %s') % str(e))
        except Exception as e:
            _logger.error(f"Unexpected error calling API {endpoint}: {str(e)}")
            raise UserError(_('Unexpected error calling DGII API: %s') % str(e))

    def copy(self, default=None):
        # Asegúrate de que 'default' sea un diccionario para evitar errores
        if default is None:
            default = {}

        # Elimina la relación itx_xml_data_id al duplicar
        default['itx_xml_data_id'] = False  # Mantiene vacío al duplicar

        # Llama al método original para duplicar el registro
        return super(AccountMove, self).copy(default=default)


    @api.model
    def create_xml_data(self, invoice, xml_content):
        # Crear un nuevo registro en itx.xml.data.dgii
        xml_data = self.env['itx.xml.data.dgii'].create({
            'name': invoice.l10n_latam_document_number,
            'xml_data': xml_content, 
            'account_move_id': invoice.id,  # Asocia el XML con la factura
            'status': 'pending',  # Establece el estado inicial
        })

        # Asigna el registro creado a itx_xml_data_id en account.move
        invoice.itx_xml_data_id = xml_data.id 

        return xml_data


    def _is_l10n_do_dgii_allowed_document(self):
        self.ensure_one()
        _logger.debug("[_is_allowed %s] Checking if document is allowed for DGII...", self.name)

        # Si no es factura electrónica o no es diario dgii, no está permitida
        if not self.is_ecf_invoice:
            _logger.debug("[_is_allowed %s] SKIPPED: is_ecf_invoice=False", self.name)
            return False
        if not self.journal_id.is_dgii:
            _logger.debug("[_is_allowed %s] SKIPPED: journal.is_dgii=False", self.name)
            return False

        # Obtener tipo desde l10n_latam_document_type_id (no desde el número asignado que puede ser TEMP-)
        doc_type = self.l10n_latam_document_type_id
        if not doc_type:
            _logger.debug("[_is_allowed %s] SKIPPED: no document type set", self.name)
            return False

        # Extraer código del prefijo (ej: 'E32' -> '32', 'E31' -> '31')
        prefix = doc_type.doc_code_prefix or ''
        if not prefix.startswith('E'):
            _logger.debug("[_is_allowed %s] SKIPPED: prefix '%s' doesn't start with 'E'", self.name, prefix)
            return False

        # Extraer los 2 dígitos después de la E
        tipo_ecf = prefix[1:3] if len(prefix) >= 3 else ''
        _logger.debug("[_is_allowed %s] Extracted type: '%s' from prefix '%s'", self.name, tipo_ecf, prefix)

        flujo = "ventas" if self.move_type.startswith("out_") else "compras"
        _logger.debug("[_is_allowed %s] Flow: %s, Type: %s", self.name, flujo, tipo_ecf)

        if flujo == "ventas":
            is_allowed = tipo_ecf in self.E_CF_VENTAS or tipo_ecf in self.E_CF_AJUSTES
        elif flujo == "compras":
            is_allowed = tipo_ecf in self.E_CF_COMPRAS or tipo_ecf in self.E_CF_AJUSTES
        else:
            is_allowed = False

        _logger.info("[_is_allowed %s] Result: %s (type=%s, flow=%s)", self.name, is_allowed, tipo_ecf, flujo)
        return is_allowed

    def action_post(self):
        """
        Flujo DGII unificado siguiendo el patrón de WebPOS:
        1. Ejecutar super() para crear asiento contable (ya asigna TEMP-{id} en _post)
        2. Validar requisitos DGII (_validate_dgii_invoice)
        3. Llamar API (submit_invoice)
        4. Si éxito y tiene TEMP-, consumir secuencia real
        5. Si error, lanzar UserError (secuencia no consumida porque está en TEMP-)
        """
        _logger.info("=" * 80)
        _logger.info("DGII action_post START for ids: %s", self.ids)
        _logger.info("=" * 80)

        # Primero, ejecutar el método original para crear el asiento contable.
        # _post() en l10n_do_dgii_fix_report_invoice_an ya asignó TEMP-{id} si es DGII ECF.
        _logger.info("[STEP 1] Calling super().action_post() to create accounting entries...")
        res = super(AccountMove, self).action_post()
        _logger.info("[STEP 1] super().action_post() completed. res: %s", res)

        # Obtener las facturas (self puede ser un recordset de una o varias facturas)
        invoices = self.env["account.move"].browse(self.ids)
        _logger.info("[STEP 2] Processing %d invoices...", len(invoices))

        for invoice in invoices:
            _logger.info("-" * 60)
            _logger.info("[INVOICE %s] Processing invoice ID=%s", invoice.name, invoice.id)
            _logger.info("[INVOICE %s] l10n_latam_document_number=%s", invoice.name, invoice.l10n_latam_document_number)
            _logger.info("[INVOICE %s] journal_id=%s, is_dgii=%s", invoice.name, invoice.journal_id.id, getattr(invoice.journal_id, 'is_dgii', False))

            # Verificar si el documento está permitido para DGII
            _logger.info("[INVOICE %s] Checking _is_l10n_do_dgii_allowed_document()...", invoice.name)
            if not invoice._is_l10n_do_dgii_allowed_document():
                _logger.warning(
                    "[INVOICE %s] SKIPPED: type %s not allowed for DGII",
                    invoice.name,
                    invoice.l10n_latam_document_number[1:3] if invoice.l10n_latam_document_number else "N/A"
                )
                continue
            _logger.info("[INVOICE %s] Document is allowed for DGII", invoice.name)

            # Validar requisitos DGII antes de procesar (RNC, impuestos, etc.)
            _logger.info("[INVOICE %s] STEP 3: Validating _validate_dgii_invoice()...", invoice.name)
           
           invoice._validate_dgii_invoice()

           doc_type = invoice.doc_type_E(invoice)
           xml_content, xml_name = invoice.build_xml_to_print(invoice, doc_type)
           xml_data = xml_content
           _logger.info(xml_name + " ->>> " + xml_data[0:100])
           try:
               execute_EF = invoice.create_xml_data(invoice, xml_data)
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
                   _logger.info("[INVOICE %s] Updated invoice with real number", invoice.name)
                   if invoice.itx_xml_data_id:
                       invoice.itx_xml_data_id.name = document_number
                       _logger.info("[INVOICE %s] Updated XML record name", invoice.name)
           except Exception as e:
               _logger.error("[INVOICE %s] ERROR: %s", invoice.name, str(e))
               raise UserError(_("Error procesando factura DGII: %s") % str(e))


            # Obtener credenciales DGII
            _logger.info("[INVOICE %s] STEP 4: Getting DGII credentials...", invoice.name)
            fe_credential = invoice.company_id.fe_dgii_id[:1]
            if not fe_credential:
                _logger.warning("[INVOICE %s] SKIPPED: No DGII FE credentials found for company %s", invoice.name, invoice.company_id.name)
                continue
            _logger.info("[INVOICE %s] Found credentials: %s, mode=%s", invoice.name, fe_credential.name, fe_credential.dgii_client_mode)

            # FLUJO UNIFICADO: Test y Producción usan el mismo método submit_invoice
            _logger.info("[INVOICE %s] STEP 5: Processing via unified API flow (mode=%s)...",
                        invoice.name, fe_credential.dgii_client_mode)

            try:
                # Preparar datos para API
                _logger.info("[INVOICE %s] STEP 6: Preparing invoice data for API...", invoice.name)
                invoice_data_for_api = invoice._prepare_invoice_data_for_api(invoice)
                lines_for_summary = invoice_data_for_api.get('lines') or []
                invoice_data_for_api['tax_summary'] = self.env[
                    'itx.xml.data.dgii'
                ]._calculate_tax_summary(invoice, lines_for_summary)
                doc_type = invoice.doc_type_E(invoice)
                _logger.info("[INVOICE %s] Prepared data: doc_type=%s, lines=%d", invoice.name, doc_type, len(lines_for_summary))

                # Llamar al API
                _logger.info("[INVOICE %s] STEP 7: Calling API submit_invoice()...", invoice.name)
                api_response = fe_credential.submit_invoice(invoice_data_for_api, doc_type)
                _logger.info("[INVOICE %s] API Response received: %s", invoice.name, api_response)

                # Manejar respuesta del API
                _logger.info("[INVOICE %s] STEP 8: Processing API response...", invoice.name)
                XmlData = self.env['itx.xml.data.dgii']
                flat_errors = api_response.get('errors') or []
                if not flat_errors and api_response.get('validation_errors'):
                    for e in api_response['validation_errors']:
                        if isinstance(e, dict):
                            flat_errors.append(e.get('message') or str(e))
                        else:
                            flat_errors.append(str(e))
                _logger.info("[INVOICE %s] Flat errors extracted: %s", invoice.name, flat_errors)

                is_success = api_response.get('success') or api_response.get('status') in ('valid_xsd', 'PROCESSED', 'PENDING')
                _logger.info("[INVOICE %s] Success check: success=%s, status=%s, is_success=%s",
                            invoice.name, api_response.get('success'), api_response.get('status'), is_success)

                if is_success:
                    # ÉXITO: Guardar XML y consumir secuencia real si estaba en TEMP-
                    _logger.info("[INVOICE %s] STEP 9: SUCCESS - Saving XML data...", invoice.name)
                    xml_vals = {
                        'xml_data': api_response.get('xml_content', api_response.get('signed_xml', '')),
                        'dgi_status': 'VALIDADO XSD' if fe_credential.dgii_client_mode == 'test' else 'ENVIADO',
                        'dgi_err_msg': False,
                        'status': 'procesed',
                        'track_id': api_response.get('track_id') or False,
                    }

                    if invoice.itx_xml_data_id:
                        invoice.itx_xml_data_id.write(xml_vals)
                        _logger.info("[INVOICE %s] Updated existing itx_xml_data_id=%s", invoice.name, invoice.itx_xml_data_id.id)
                    else:
                        rec = XmlData.create({
                            'name': invoice.l10n_latam_document_number or invoice.name or 'DGII',
                            'account_move_id': invoice.id,
                            **xml_vals,
                        })
                        invoice.itx_xml_data_id = rec.id
                        _logger.info("[INVOICE %s] Created new itx_xml_data_id=%s", invoice.name, rec.id)

                    # Si tiene TEMP-, consumir secuencia real (igual que WebPOS)
                    _logger.info("[INVOICE %s] STEP 10: Checking for TEMP- sequence consumption...", invoice.name)
                    _logger.info("[INVOICE %s] Current l10n_latam_document_number=%s, starts_with_TEMP=%s",
                                invoice.name, invoice.l10n_latam_document_number,
                                invoice.l10n_latam_document_number.startswith("TEMP-") if invoice.l10n_latam_document_number else False)

                    if invoice.l10n_latam_document_number and invoice.l10n_latam_document_number.startswith("TEMP-"):
                        _logger.info("[INVOICE %s] Consuming real fiscal sequence...", invoice.name)
                        _logger.info("[INVOICE %s] fiscal_sequence_id=%s", invoice.name, invoice.l10n_do_fiscal_sequence_id.id if invoice.l10n_do_fiscal_sequence_id else None)

                        if invoice.l10n_do_fiscal_sequence_id:
                            document_number = invoice.l10n_do_fiscal_sequence_id.get_fiscal_number()
                            _logger.info("[INVOICE %s] Got fiscal number: %s", invoice.name, document_number)

                            invoice.write({
                                "l10n_latam_document_number": document_number,
                                "payment_reference": f"{invoice.name} - {document_number}",
                            })
                            _logger.info("[INVOICE %s] Updated invoice with real number", invoice.name)

                            if invoice.itx_xml_data_id:
                                invoice.itx_xml_data_id.name = document_number
                                _logger.info("[INVOICE %s] Updated XML record name", invoice.name)
                        else:
                            _logger.error("[INVOICE %s] ERROR: No fiscal sequence ID found!", invoice.name)
                    else:
                        _logger.info("[INVOICE %s] No TEMP- prefix, skipping sequence consumption", invoice.name)

                    _logger.info("[INVOICE %s] COMPLETED SUCCESSFULLY (mode=%s, track_id=%s).",
                                 invoice.name, fe_credential.dgii_client_mode,
                                 api_response.get('track_id'))
                else:
                    # ERROR: Guardar error pero NO consumir secuencia (ya está en TEMP-)
                    _logger.error("[INVOICE %s] API returned error status", invoice.name)
                    error_message = (
                        _("Errores de validación/envío:\n%s") % "\n".join(flat_errors)
                        if flat_errors
                        else api_response.get('message', _('Error desconocido durante el procesamiento.'))
                    )
                    xml_vals = {
                        'xml_data': api_response.get('xml_content', api_response.get('signed_xml', '')),
                        'dgi_status': 'ERROR',
                        'dgi_err_msg': error_message,
                        'status': 'error',
                    }
                    if invoice.itx_xml_data_id:
                        invoice.itx_xml_data_id.write(xml_vals)
                    else:
                        rec = XmlData.create({
                            'name': invoice.l10n_latam_document_number or invoice.name or 'ERROR',
                            'account_move_id': invoice.id,
                            **xml_vals,
                        })
                        invoice.itx_xml_data_id = rec.id

                    _logger.error("[INVOICE %s] RAISING USER ERROR: %s", invoice.name, error_message)
                    raise UserError(error_message)

            except UserError:
                _logger.error("[INVOICE %s] UserError propagated", invoice.name)
                raise
            except Exception as e:
                _logger.error("[INVOICE %s] EXCEPTION: %s", invoice.name, str(e), exc_info=True)
                raise UserError(_("Error procesando factura DGII: %s") % str(e))

        _logger.info("=" * 80)
        _logger.info("DGII action_post COMPLETED for ids: %s", self.ids)
        _logger.info("=" * 80)
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
            # Create a new instance of the ItxXMLDataDGII model
            my_data = self.env['itx.xml.data.dgii'].create({
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
                'vat': ''.join(filter(str.isdigit, invoice.partner_id.vat or '')),
                'street': invoice.partner_id.street or '',
                'city': invoice.partner_id.city or '',
                'state_name': invoice.partner_id.state_id.name if invoice.partner_id.state_id else '',
                'country_name': invoice.partner_id.country_id.name if invoice.partner_id.country_id else '',
                'email': invoice.partner_id.email or '',
                'commercial_partner_id': {
                    'name': (
                        invoice.partner_id.commercial_partner_id.name
                        or invoice.partner_id.name
                        or ''
                    ),
                },
            }

            # Prepare currency data
            currency_data = {
                'id': invoice.currency_id.id,
                'name': invoice.currency_id.name or '',
                'decimal_places': invoice.currency_id.decimal_places or 2,
                'inverse_rate': invoice._get_fiscal_rate()
            }

            # Datos de compañía para plantillas QWeb (Emisor): nombre, RNC, dirección, etc.
            comp = invoice.company_id
            company_data = {
                'name': comp.name or '',
                'vat': ''.join(filter(str.isdigit, comp.vat or '')),
                'street': comp.street or '',
                'city': comp.city or '',
                'state_id': {'name': comp.state_id.name or ''} if comp.state_id else {'name': ''},
                'partner_id': {
                    'name': comp.partner_id.name or '' if comp.partner_id else '',
                    'commercial_partner_id': {
                        'name': (
                            (comp.partner_id.commercial_partner_id.name or comp.partner_id.name or '')
                            if comp.partner_id
                            else ''
                        ),
                    },
                },
            }
            if hasattr(comp, 'fe_dgii_id') and comp.fe_dgii_id:
                fe = comp.fe_dgii_id[:1]
                company_data['fe_dgii_id'] = [{
                    'name': fe.name or comp.name or '',
                    'active': fe.active,
                }]
            else:
                company_data['fe_dgii_id'] = [{
                    'name': comp.name or '',
                    'active': True,
                }]

            # Prepare invoice lines data
            lines_data = []
            for line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                line_taxes = []
                for tax in line.tax_ids:
                    tax_data = {
                        'name': tax.name or '',
                        'amount': tax.amount or 0.0,
                        'price_include': tax.price_include or False,
                        'tax_group_id': tax.tax_group_id.id if tax.tax_group_id else False
                    }
                    # Código tipo impuesto DGII (plantillas/API leen `tipo_impuesto_dgii`)
                    if tax.tax_group_id and tax.tax_group_id.name == 'ITBIS' and tax.amount > 0:
                        if tax.tipo_impuesto_dgii:
                            tax_data['tipo_impuesto_dgii'] = tax.tipo_impuesto_dgii
                    elif getattr(tax, 'tipo_impuesto_dgii', None):
                        tax_data['tipo_impuesto_dgii'] = tax.tipo_impuesto_dgii
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

            # Calculate e-CF modification code automatically for DGII
            ecf_modification_code = self._get_dgii_ecf_modification_code(invoice)
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
                'amount_total': invoice.amount_total,
                'amount_untaxed': invoice.amount_untaxed,
                'amount_tax': invoice.amount_tax,
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
                'amount_total': invoice.amount_total,
                'amount_untaxed': invoice.amount_untaxed,
                'amount_tax': invoice.amount_tax,
            }

        except Exception as e:
            _logger.error(f"Error preparing invoice data for API: {str(e)}")
            raise UserError(_('Error preparing invoice data: %s') % str(e))

    def build_xml_to_print(self, invoice, type_document):
        """Generate XML using the dgii_api endpoint with comprehensive logging"""
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
            _logger.info("Journal is DGII: %s", invoice.journal_id.is_dgii)
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
            
            # Call the dgii_api generate_xml endpoint
            api_data = {
                'invoice_data': invoice_data,
                'type_document': type_document
            }
            
            _logger.info("Calling DGII API with type_document: %s", type_document)
            _logger.info("API Request Data: %s", json.dumps(api_data, indent=2))
            
            response = self._call_dgii_api('/dgii/v1/generate_xml', api_data)
            
            # Log the full API response
            _logger.info("DGII API Response:")
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
        Tipo de documento para API DGII / XSD: solo E31–E47 (e-CF).
        El tipo se infiere del prefijo E## del e-NCF (p. ej. E320000000001 → E32).
        """
        import re

        if invoice.l10n_latam_document_number:
            num = invoice.l10n_latam_document_number.strip()
            _logger.info("doc_type_E: document number %s", num)
            ncf_match = re.match(r'^(E\d{2})', num, re.IGNORECASE)
            if ncf_match:
                ncf_prefix = ncf_match.group(1).upper()
                # Ya no usamos mapeo; el prefijo E## es directamente el tipo.
                doc_type = ncf_prefix
                _logger.info(
                    "doc_type_E: resuelto desde e-NCF prefijo %s → %s",
                    ncf_prefix,
                    doc_type,
                )
                return doc_type

        raise UserError(
            _("No se pudo determinar el tipo e-CF (E31–E47) para %s. "
              "Asegúrese de que el e-NCF comience con E## (Ej: E320000000016).")
            % (invoice.display_name,)
        )

    # funciones heredadas de itx_xml_data_id
    def action_resend_xml(self):
        self.itx_xml_data_id.action_resend_xml()

    def rebuild_xml_to_send(self):
        # Verifica si existe un registro de itx.xml.data.dgii asociado
        if not self.itx_xml_data_id:
            # Si no existe, crea un nuevo registro en itx.xml.data.dgii
            # Determine document type based on current invoice characteristics
            doc_type = self.doc_type_E(self) # Pass the invoice object
            _logger.info("EX444 0 doctype rebuild {doc_type}")
            xml_content, xml_name = self.build_xml_to_print(self, doc_type)  # Genera el contenido XML
            xml_data = self.env['itx.xml.data.dgii'].create({
                'name': self.l10n_latam_document_number,  # O el campo que desees usar
                'xml_data': xml_content,
                'account_move_id': self.id,  # Asocia el XML con la factura
                'status': 'pending',  # Establece el estado inicial
            })
            self.itx_xml_data_id = xml_data.id  # Asigna el nuevo registro al campo itx_xml_data_id
        
        self.itx_xml_data_id.rebuild_xml_to_send()

    def action_verify_sent_encf(self):
        self.itx_xml_data_id.action_verify_sent_encf()

    def action_manual_resend_dgii(self):
        """
        Manual action to resend DGII documents that were not processed initially.
        This method performs the complete DGII sending process:
        1. Validates invoice eligibility
        2. Creates XML data if it doesn't exist
        3. Sends XML to DGII API
        4. Verifies the sent document
        """
        self.ensure_one()

        # Validate invoice eligibility for DGII
        if not (self.is_ecf_invoice and self.journal_id.is_dgii and self.l10n_latam_document_number and self.journal_id.l10n_latam_use_documents):
            raise UserError(_('Esta factura no es elegible para envío DGII. Debe ser una factura electrónica en un diario DGII con número fiscal válido.'))

        # Check document type validation using the new unified method
        if not self._is_l10n_do_dgii_allowed_document():
            raise UserError(
                _("El tipo de documento %s (%s) no está permitido en el diario %s para el flujo de %s.")
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
            if not self.itx_xml_data_id:
                _logger.info("Creating XML data for manual DGII resend of invoice %s", self.id)
                doc_type = self.doc_type_E(self)
                xml_content, xml_name = self.build_xml_to_print(self, doc_type)

                xml_data = self.env['itx.xml.data.dgii'].create({
                    'name': self.l10n_latam_document_number,
                    'xml_data': xml_content,
                    'account_move_id': self.id,
                    'status': 'pending',
                })
                self.itx_xml_data_id = xml_data.id
            else:
                _logger.info("Using existing XML data for manual DGII resend of invoice %s", self.id)

            # Send XML to DGII
            _logger.info("Sending XML to DGII for invoice %s", self.id)
            self.itx_xml_data_id.save_and_send_xml()

            # Verify sent document
            _logger.info("Verifying sent document for invoice %s", self.id)
            self.itx_xml_data_id.verify_sent_encf()

            # Log success
            _logger.info("Manual DGII resend completed successfully for invoice %s", self.id)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Éxito'),
                    'message': _('Documento reenviado exitosamente a DGII.'),
                    'type': 'success',
                }
            }

        except Exception as e:
            _logger.error("Error in manual DGII resend for invoice %s: %s", self.id, str(e))
            raise UserError(_('Error al reenviar documento a DGII: %s') % str(e))


    # fin mapeo funciones heredadas de itx_xml_data_id


## REVISAR constraints para evitar duplicado de impuestos en la lineas de factura

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    _description = 'Herencia para validar impuestos únicos por grupo en líneas de DGII'

    @api.constrains('tax_ids')
    def _check_single_tax_per_group_dgii(self):
        """Ensure only one tax per tax_group_id is applied to invoice lines for DGII."""
        for line in self:
            # Only validate for DGII journals and when invoice is posted or being posted
            if (line.tax_ids and line.move_id and line.move_id.journal_id.is_dgii and
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
                        _("No puede haber más de un impuesto del mismo grupo por línea en facturas DGII:\n%s") %
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
                #                     _("You cannot validate and invoice of Fiscal Type "
                #                       "Regímen Especial with ITBIS/ISC.\n\n"
                #                       "See DGII General Norm 05-19, Art. 3 for further "
                #                       "information")
                #                 )