# Part of Odoo. See LICENSE file for full copyright and licensing details.

import io
import os
import requests
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round, float_is_zero
from odoo.tools import html2plaintext

import logging
_logger = logging.getLogger(__name__)

# Activar en Ajustes > Técnico > Parámetros del sistema: l10n_do_dgii_fe_base.debug_report_qr = true
# para loguear también cuando el sello existe (vista previa truncada).
ICP_DEBUG_REPORT_QR = 'l10n_do_dgii_fe_base.debug_report_qr'

import datetime


class AccountMove(models.Model):
    _inherit = 'account.move'
    _description = 'Herencia para editar el post de la factura dgii'

    # Mapeo de tipos E-CF para DGII (solo prefijos numéricos E##; sin serie B / sin fallback FF|FC)
    E_CF_VENTAS = ["31", "32", "44", "45", "46"]
    E_CF_COMPRAS = ["41", "43", "47"]
    E_CF_AJUSTES = ["33", "34"]

    # Tipos e-CF admitidos por la API unificada DGII (E31–E47 según catálogo).
    _VALID_ECF_API_TYPES = frozenset({
        'E31', 'E32', 'E33', 'E34', 'E41', 'E43', 'E44', 'E45', 'E46', 'E47',
    })

    itx_dgii_xml_data_raw = fields.Text('XML Data Raw')
    itx_xml_data_ids = fields.One2many('itx.xml.data.dgii', 'account_move_id', string='XML Data ids')


    itx_xml_data_id = fields.Many2one('itx.xml.data.dgii', string='XML Data Link', ondelete='set null')

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
    itx_dgii_xml_data = fields.Text(related='itx_xml_data_id.xml_data', string='XML Data DGII', store=True)
    itx_dgii_status = fields.Selection(related='itx_xml_data_id.status', string='DGII Status', store=True)
    itx_dgii_dgi_status = fields.Char(related='itx_xml_data_id.dgi_status', string='Estado DGII', store=True)
    itx_dgii_dgi_err_msg = fields.Text(related='itx_xml_data_id.dgi_err_msg', string='DGII Error Message', store=True)
    # itx_dgii_json_response = fields.Text(related='itx_xml_data_id.json_response', string='Json Response DGII')  # Descomentar si es necesario

    

    # Campo para sello electrónico QR DGII (related para consistencia)
    itx_dgii_electronic_stamp = fields.Char(
        related='itx_xml_data_id.qr_code',
        string="DGII Electronic Stamp",
        store=True,
        help=(
            "URL/cadena para el QR en PDF. **Fuente canónica:** respuesta del API (campo qr_code / "
            "electronic_stamp / etc.); se guarda en itx.xml.data.dgii. Fallback opcional en Odoo solo "
            "para RFCE (ConsultaTimbreFC) si el parámetro l10n_do_dgii_fe_base.qr_local_fallback está activo."
        ),
    )


    itx_dgii_electronic_stamp_encoded = fields.Char(
        compute="_compute_qr_encoded"
    )


    is_dgii = fields.Boolean(
        related='journal_id.is_dgii',
        store=True,
    )
    # Campos para facturación electrónica DGII, mover cerca de itx_dgii_electronic_stamp_encoded    
    l10n_do_ecf_security_code = fields.Char(string="e-CF Security Code", copy=False)
    l10n_do_ecf_sign_date = fields.Datetime(string="e-CF Sign Date", copy=False)
    

    # Reporte / layout: valor QR desde sello DGII (`itx_dgii_electronic_stamp`).
    l10n_do_dgii_report_has_qr = fields.Boolean(
        compute='_compute_l10n_do_dgii_report_qr',
        string='Mostrar QR DGII en reporte',
    )
    l10n_do_dgii_report_qr_src = fields.Char(
        compute='_compute_l10n_do_dgii_report_qr',
        string='Valor para parámetro value del QR (report/barcode)',
    )

    @api.depends('itx_xml_data_id', 'itx_xml_data_id.qr_code')
    def _compute_l10n_do_dgii_report_qr(self):
        for rec in self:
            # qr_code ya se guarda con url_quote_plus (cf. _apply / _build_fc); no aplicar quote otra vez.
            val = (rec.itx_xml_data_id.qr_code or '').strip() if rec.itx_xml_data_id else ''
            rec.l10n_do_dgii_report_has_qr = bool(val)
            rec.l10n_do_dgii_report_qr_src = val

    @api.depends(
        'itx_xml_data_id',
        'itx_xml_data_id.qr_code',
        'is_ecf_invoice',
        'journal_id.is_dgii',
    )
    def _compute_qr_encoded(self):
        _icp = self.env['ir.config_parameter'].sudo().get_param(ICP_DEBUG_REPORT_QR, 'False')
        debug_qr = str(_icp if _icp is not None else 'False').lower() in (
            '1',
            'true',
            'yes',
            'on',
        )
        for rec in self:
            # Alias para el endpoint barcode: un solo nivel de codificación.
            val = (
                (rec.itx_xml_data_id.qr_code or '').strip()
                if rec.itx_xml_data_id
                else ''
            )
            rec.itx_dgii_electronic_stamp_encoded = val
            j_dgii = getattr(rec.journal_id, 'is_dgii', False)
            if not (rec.is_ecf_invoice and j_dgii):
                continue
            if not val:
                xml = rec.itx_xml_data_id
                _logger.info(
                    '[DGII][report_qr] sin sello usable en reporte | move_id=%s name=%s state=%s '
                    'is_ecf_invoice=%s journal_is_dgii=%s itx_xml_data_id=%s raw_qr_len=%s '
                    'latam_doc=%s ref=%s sec_code_len=%s',
                    rec.id,
                    rec.name,
                    rec.state,
                    rec.is_ecf_invoice,
                    j_dgii,
                    xml.id if xml else None,
                    len((xml.qr_code or '').strip()) if xml else 0,
                    rec.l10n_latam_document_type_id.display_name
                    if rec.l10n_latam_document_type_id
                    else None,
                    rec.ref,
                    len((rec.l10n_do_ecf_security_code or '').strip()),
                )
            elif debug_qr:
                _logger.info(
                    '[DGII][report_qr] sello presente | move_id=%s stamp_len=%s head=%s',
                    rec.id,
                    len(val),
                    (val[:120] + '...') if len(val) > 120 else val,
                )



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

    def _dgii_amount_total_in_dop(self):
        """
        ``amount_total`` de la factura expresado en DOP (tasa fiscal / umbral 250k DGII).
        Misma base que ``_dgii_e32_is_rfce_simplified`` y que ``itx_dgii_api`` para RFCE.
        """
        self.ensure_one()
        amount_total = float(self.amount_total or 0.0)
        cur = (self.currency_id.name or '').strip().upper()
        try:
            inv_rate = float(self._get_fiscal_rate() or 0.0)
        except (TypeError, ValueError):
            inv_rate = 0.0
        if cur and cur != 'DOP' and inv_rate > 0:
            return amount_total * inv_rate
        return amount_total

    @staticmethod
    def _dgii_plain_invoice_line_label(line):
        """Campo ``name`` de la línea sin HTML (etiqueta visible)."""
        raw = line.name or ''
        return (html2plaintext(raw).strip() if raw else '')

    def get_clean_description(self, line):
        """Texto para DGII ``NombreItem``.

        En diarios DGII la etiqueta obligatoria al confirmar (``_validate_dgii_invoice``).

        * Sin producto: solo ``line.name`` (texto plano).
        * Con producto: si la etiqueta contiene el nombre del producto (típico autofill), se
          usa el nombre del producto; si no, la etiqueta tal cual.
        """
        # Solo líneas facturables (``display_type == 'product'``): secciones/notas no tienen NombreItem.
        if line.display_type != 'product':
            return ''  # No enviar secciones o notas al API

        product = line.product_id
        line_name = self._dgii_plain_invoice_line_label(line)

        # Sin producto: sólo etiqueta (obligatoria al confirmar si diario DGII).
        if not product:
            description = line_name
            if len(description) > 80:
                description = description[:77] + '...'
            return description

        product_name = (product.name or '').strip()
        if product_name and line_name and product_name in line_name:
            description = product_name
        else:
            description = line_name

        description = (description or '').strip()
        if len(description) > 80:
            description = description[:77] + '...'

        return description

    def _get_dgii_ecf_modification_code(self, invoice):
        """
        Código DGII ``CodigoModificacion`` (InformacionReferencia) para NC/ND.

        Nota de **crédito** (``out_refund``): misma heurística habitual —
        total NC ≈ total factura origen → ``1`` (anula el NCF modificado);
        NC menor → ``3`` (corrección de montos parcial).

        Nota de **débito** (``out_debit``): mora, intereses, cargos adicionales referidos
        a una factura — **no** es anulación del comprobante origen. DGII encaja en
        ``3`` (corrige montos). Comparar ND vs total origen y devolver ``1`` sería
        incorrecto en la práctica (coincidencia numérica ≠ anulación).

        Si existe ``l10n_do_ecf_modification_code`` en el move (otros módulos), se respeta.
        """
        # Only apply to credit notes (out_refund) and debit notes (out_debit)
        if invoice.move_type not in ('out_refund', 'out_debit'):
            return ''

        manual = getattr(invoice, 'l10n_do_ecf_modification_code', None)
        if manual not in (None, False, ''):
            sm = str(manual).strip()
            try:
                n = int(sm)
            except (ValueError, TypeError):
                n = None
            if n is not None and 1 <= n <= 5:
                return str(n)

        # Get the original invoice
        original_invoice = None
        if invoice.move_type == 'out_refund' and invoice.reversed_entry_id:
            original_invoice = invoice.reversed_entry_id
        elif invoice.move_type == 'out_debit' and invoice.debit_origin_id:
            original_invoice = invoice.debit_origin_id

            

        if not original_invoice:
            origin_ncf = (getattr(invoice, 'l10n_do_origin_ncf', None) or '').strip()
            if origin_ncf:
                original_invoice = invoice.env['account.move'].sudo().search(
                    [('l10n_latam_document_number', '=', origin_ncf)], limit=1
                )

        if not original_invoice:
            _logger.warning(f"Cannot determine modification code: no original invoice found for {invoice.name}")
            if invoice.move_type == 'out_debit' and (getattr(invoice, 'l10n_do_origin_ncf', None) or '').strip():
                return '3'
            return ''

        epsilon = 0.01

        if invoice.move_type == 'out_debit':
            return '3'

        # out_refund: compare amounts using absolute values (negative amounts en refunds)
        current_amount = abs(invoice.amount_total)
        original_amount = abs(original_invoice.amount_total)
        if abs(current_amount - original_amount) < epsilon:
            return '1'
        return '3'

    def _validate_dgii_invoice(self):
        """Valida todos los requisitos de DGII antes de confirmar la factura.

        Recoge todos los errores y los muestra juntos al final.
        Solo aplica para diarios DGII.
        """
        if not self.journal_id.is_dgii:
            return

        errors = []

        # Ítems facturables solamente: ``line_section`` / ``line_note`` (secciones y notas)
        # no son DetallesItems e-CF; no validar ni enviar como líneas DGII.
        product_lines = self.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note'))

        # Etiqueta (line.name) obligatoria: XSD NombreItem AlfNum80Type minLength 1; no usar placeholder.
        for line in product_lines:
            if not self._dgii_plain_invoice_line_label(line):
                hint = (
                    line.product_id.display_name
                    if line.product_id
                    else _('línea sin producto')
                )
                errors.append(
                    _(
                        '- La etiqueta / descripción de la línea no puede estar vacía '
                        '(producto: %s). Complétela en la columna de etiqueta antes de confirmar.'
                    )
                    % hint
                )

        # 1. Validar RNC/Cédula para facturas >= RD$250,000 (umbral en DOP, no en moneda extranjera)
        amount_dop = self._dgii_amount_total_in_dop()
        if amount_dop >= 250000:
            if not self.partner_id.vat or not self.partner_id.vat.strip():
                errors.append(
                    _("- Cliente sin RNC/Cédula: Para facturas >= RD$250,000 es obligatorio.")
                )

        # 2. Validar que cada línea tenga al menos un impuesto
        for line in product_lines:
            if not line.tax_ids:
                errors.append(
                    _("- Línea '%s' no tiene impuestos configurados. "
                      "Cada línea debe tener al menos un impuesto (ej: ITBIS 18 o exento).")
                    % (self._dgii_plain_invoice_line_label(line) or line.product_id.display_name or '')[:50]
                )

        # 2b. Monto 0: e-CF coherente con DGII (IndicadorFacturacion 0) → impuesto "No facturable" (tipo_impuesto_dgii = 4)
        currency = self.currency_id
        rounding = currency.rounding if currency else 0.01
        gravado_tipos_dgii = {'1', '2', '3', '5'}
        for line in product_lines:
            if not line.tax_ids:
                continue
            if not float_is_zero(line.price_subtotal, precision_rounding=rounding):
                continue
            label = (
                self._dgii_plain_invoice_line_label(line)
                or (line.product_id.display_name if line.product_id else '')
                or _('línea')
            )[:80]
            bad_grav = line.tax_ids.filtered(lambda t: t.tipo_impuesto_dgii in gravado_tipos_dgii)
            if bad_grav:
                errors.append(
                    _(
                        '- Línea "%(line)s" tiene monto 0 y lleva impuesto(s) gravados DGII (%(taxes)s). '
                        'Sustitúyalos por el impuesto con Tipo de Impuesto DGII '
                        '"No facturable (Hoteles y/o Restaurantes)" (código 4).'
                    )
                    % {
                        'line': label,
                        'taxes': ', '.join(bad_grav.mapped('name'))[:200],
                    }
                )
            if not line.tax_ids.filtered(lambda t: t.tipo_impuesto_dgii == '4'):
                errors.append(
                    _(
                        '- Línea "%(line)s" tiene monto 0: debe incluir un impuesto con '
                        'Tipo de Impuesto DGII "No facturable (Hoteles y/o Restaurantes)" (código 4).'
                    )
                    % {'line': label}
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
        return self.env['ir.config_parameter'].sudo().get_param('dgii_api.base_url', 'http://localhost:8069')

    def _call_dgii_api(self, endpoint, data):
        """Make a JSON-RPC call to the dgii_api endpoints."""
        _logger.info("DGII API Call - Starting API call to endpoint: %s", endpoint)
        cre = self.company_id.fe_dgii_id.filtered(lambda p: p.active)[:1]
        _logger.info("DGII API Call - Company credential found: %s", bool(cre))
        
        path = endpoint.replace('/dgii/v1/', '').lstrip('/')
        if not path:
            path = endpoint.lstrip('/')
            
        _logger.info("DGII API Call - Endpoint: %s, Path: %s", endpoint, path)
        _logger.debug("DGII API Call - Data payload: %s", json.dumps(data, default=str)[:500] + "..." if len(json.dumps(data, default=str)) > 500 else json.dumps(data, default=str))
        
        try:
            if cre:
                _logger.info("DGII API Call - Using company credentials for authentication")
                _logger.debug("DGII API Call - Company credential details - RNC: %s, Client ID: %s, Has API Key: %s, Environment: %s, Client Mode: %s", 
                             getattr(cre, 'rnc', 'N/A'), 
                             getattr(cre, 'api_client_id', 'N/A'), 
                             bool(getattr(cre, 'api_key', None)),
                             getattr(cre, 'dgii_environment', 'N/A'),
                             getattr(cre, 'dgii_client_mode', 'N/A'))
                
                # Force usage of API Key for all requests in production-like environment
                # so that X-API-Key header is sent.
                _logger.info("DGII API Call - Preparing auth params")
                params = cre._api_params_with_auth(data)
                _logger.debug("DGII API Call - Auth params: %s", json.dumps(params, default=str))
                
                _logger.info("DGII API Call - Making JSON-RPC call with API key authentication")
                result = cre._api_jsonrpc(
                    path,
                    params,
                    use_api_key=True,
                    timeout=30,
                )
                _logger.info("DGII API Call - Successful response received")
                _logger.debug("DGII API Call - Response result: %s", json.dumps(result, default=str)[:500] + "..." if len(json.dumps(result, default=str)) > 500 else json.dumps(result, default=str))
                return {'jsonrpc': '2.0', 'id': 1, 'result': result}
                
            _logger.info("DGII API Call - Using fallback method (no company credentials)")
            base_url = self._get_api_base_url()
            url = f"{base_url.rstrip('/')}{endpoint}"
            _logger.info("DGII API Call - Base URL: %s, Full URL: %s", base_url, url)
            
            jsonrpc_data = {
                'jsonrpc': '2.0',
                'method': 'call',
                'params': data,
                'id': 1,
            }
            _logger.debug("DGII API Call - Request data: %s", json.dumps(jsonrpc_data, default=str))
            
            _logger.info("DGII API Call - Making POST request")
            response = requests.post(
                url,
                json=jsonrpc_data,
                headers={'Content-Type': 'application/json'},
                timeout=30,
            )
            _logger.info("DGII API Call - Response status code: %s", response.status_code)
            _logger.debug("DGII API Call - Response headers: %s", dict(response.headers))
            response.raise_for_status()
            result = response.json()
            _logger.info("DGII API Call - Successful JSON response received")
            _logger.debug("DGII API Call - Response JSON: %s", json.dumps(result, default=str)[:500] + "..." if len(json.dumps(result, default=str)) > 500 else json.dumps(result, default=str))
            return result
        except UserError:
            raise
        except requests.exceptions.RequestException as e:
            _logger.error('API call to %s failed: %s', endpoint, str(e))
            _logger.error('Request details - URL: %s, Data: %s', url if 'url' in locals() else 'N/A', json.dumps(data, default=str) if data else 'N/A')
            if 'response' in locals():
                _logger.error('Response details - Status code: %s, Response text: %s', 
                             response.status_code if hasattr(response, 'status_code') else 'N/A',
                             response.text if hasattr(response, 'text') else 'N/A')
            raise UserError(_('Error calling DGII API: %s') % e) from e
        except Exception as e:
            _logger.error('Unexpected error calling API %s: %s', endpoint, str(e))
            _logger.error('Error details - Data: %s', json.dumps(data, default=str) if data else 'N/A')
            raise UserError(_('Unexpected error calling DGII API: %s') % e) from e

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
        if not self.is_ecf_invoice or not self.journal_id.is_dgii:
            return False

        # Tipo desde el tipo de documento latino (no desde el número: puede ser TEMP-{id})
        doc_type = self.l10n_latam_document_type_id
        if not doc_type:
            return False
        prefix = doc_type.doc_code_prefix or ''
        if not prefix.startswith('E') or len(prefix) < 3:
            return False
        tipo_ecf = prefix[1:3]

        flujo = "ventas" if self.move_type.startswith("out_") else "compras"

        if flujo == "ventas":
            return tipo_ecf in self.E_CF_VENTAS or tipo_ecf in self.E_CF_AJUSTES
        if flujo == "compras":
            return tipo_ecf in self.E_CF_COMPRAS or tipo_ecf in self.E_CF_AJUSTES
        return False

    def _dgii_e32_is_rfce_simplified(self):
        """
        E32 consumo bajo umbral: XML ``RFCE`` + endpoint RecepcionFC.
        Misma regla que ``itx_dgii_api`` ``XmlInterface._determine_is_rfce`` (250k DOP).
        """
        self.ensure_one()
        return self._dgii_amount_total_in_dop() < 250000.0

    def action_post(self):
        # Primero, ejecutar el método original para crear el asiento contable.
        # Esto es necesario para que los campos de la factura estén correctamente
        # establecidos antes de cualquier validación o lógica específica de DGII.
        res = super(AccountMove, self).action_post()

        # Obtener las facturas (self puede ser un recordset de una o varias facturas)
        invoices = self.env["account.move"].browse(self.ids)

        for invoice in invoices:
            if not invoice._is_l10n_do_dgii_allowed_document():
                _logger.debug(
                    "DGII skipped for invoice %s: document type not allowed for DGII",
                    invoice.id,
                )
                continue
            # Validar antes de confirmar (solo para DGII y solo si es un documento permitido)
            # Esta validación ahora ocurre después de que la factura ha sido 'posteada' por el super
            invoice._validate_dgii_invoice()

            doc_type = invoice.doc_type_E(invoice)
            xml_content, xml_name = invoice.build_xml_to_print(invoice, doc_type)
            xml_data = xml_content
            try:
                execute_EF = invoice.create_xml_data(invoice, xml_data)
                # Las validaciones duplicadas aquí se eliminan ya que _validate_dgii_invoice() las maneja
                execute_EF.save_and_send_xml()
                # Only verify with DGII if the submit succeeded and a track_id is available.
                # In case of XSD/validation failures the save_and_send_xml stores the error
                # on the itx.xml.data.dgii record and does NOT raise.
                if getattr(execute_EF, 'status', None) == 'sent' and getattr(execute_EF, 'track_id', False):
                    try:
                        execute_EF.verify_sent_encf()
                    except Exception as e:
                        # Log and continue: verification can fail independently and should not
                        # block invoice posting flow here.
                        _logger.warning("DGII verification failed for invoice %s: %s", invoice.id, str(e))
                if (
                    invoice.l10n_latam_document_number
                    and invoice.l10n_latam_document_number.startswith("TEMP-")
                ):
                    document_number = (
                        invoice.l10n_do_fiscal_sequence_id.get_fiscal_number()
                    )
                    invoice.write(
                        {
                            "l10n_latam_document_number": document_number,
                            "payment_reference": f"{invoice.name} - {document_number}",
                        }
                    )
                    if invoice.itx_xml_data_id:
                        invoice.itx_xml_data_id.name = document_number
            except Exception as e:
                raise UserError(
                    _("Error al crear el documento Electronico: %s") % str(e)
                )
            invoice.xml_print_to_std(xml_content)


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

    def _prepare_payments_list_for_dgii_api(self, invoice):
        """Lista canónica para itx_dgii_api: amount + code_payment_dgii (+ id/name)."""
        self.ensure_one()
        if invoice.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
            return []
        per_payment_amount = {}
        term_lines = invoice.line_ids.filtered(
            lambda l: l.account_id.internal_type in ('receivable', 'payable')
        )
        for line in term_lines:
            for partial in (line.matched_credit_ids | line.matched_debit_ids):
                counterpart = (
                    partial.debit_move_id
                    if partial.credit_move_id == line
                    else partial.credit_move_id
                )
                move = counterpart.move_id
                if move == invoice:
                    continue
                pay = move.payment_id
                if not pay:
                    continue
                per_payment_amount[pay.id] = per_payment_amount.get(pay.id, 0.0) + float(
                    partial.amount
                )
        out = []
        for pid, amount in per_payment_amount.items():
            pay = self.env['account.payment'].browse(pid)
            code = ''
            if pay.type_payment_id:
                code = pay.type_payment_id.code_payment_dgii or ''
            out.append({
                'amount': amount,
                'code_payment_dgii': code,
                'id': pay.id,
                'name': pay.name or pay.move_id.name or '',
            })
        return out

    def _dgii_tipo_pago_from_invoice(self, invoice):
        """DGII TipoPago: 1 contado, 2 crédito, 3 gratuito."""
        v = getattr(invoice, 'l10n_do_tipo_pago', None)
        if v not in (None, False, ''):
            return str(v).strip()
        pt = invoice.invoice_payment_term_id
        if pt and any(getattr(l, 'days', 0) > 0 for l in pt.line_ids):
            return '2'
        return '1'

    def _dgii_geo_codes_for_partner(self, partner):
        """Códigos XSD ProvinciaMunicipioType para payload API (emisor/comprador).

        Orden: modelo conector (res.municipality + state.ecf_code), luego Char legacy.
        """
        out = {'dgii_municipio_code': '', 'dgii_provincia_code': ''}
        if not partner:
            return out
        muni = getattr(partner, 'res_municipality_id', None)
        if muni and getattr(muni, 'ecf_code', None):
            s = str(muni.ecf_code).strip()
            if s:
                out['dgii_municipio_code'] = s
        st = partner.state_id
        if st and getattr(st, 'ecf_code', None):
            s = str(st.ecf_code).strip()
            if s:
                out['dgii_provincia_code'] = s
        if not out['dgii_municipio_code']:
            mc = getattr(partner, 'municipio_ecf', None)
            if mc:
                out['dgii_municipio_code'] = str(mc).strip()
        if not out['dgii_provincia_code']:
            pc = getattr(partner, 'provincia_ecf', None)
            if pc:
                out['dgii_provincia_code'] = str(pc).strip()
        return out

    @api.model
    def _dgii_effective_line_taxes(self, line):
        """Impuestos efectivos de la línea (hijos si el maestro es agrupación ``group``)."""
        Tax = self.env['account.tax']
        effective = Tax.browse()
        for tax in line.tax_ids:
            if tax.amount_type == 'group' and tax.children_tax_ids:
                effective |= tax.children_tax_ids
            else:
                effective |= tax
        return effective

    def _prepare_tax_summary_for_dgii_api(self, invoice=None):
        """Totales impositivos e-CF desde Odoo (``tax_ids.compute_all``), estilo l10n_do_ecf_invoicing.

        Contrato enviado en ``invoice_data['tax_summary']`` para la API/plantillas (opción C: Odoo es la fuente).
        Claves: base_18, itbis_18, base_16, itbis_16, base_0, itbis_0, exento, total_itbis,
        itbis_retenido, isr_retenido, impuestos_adicionales (lista; reservado / vacío si no aplica).
        """
        inv = invoice or self
        inv.ensure_one()
        currency = inv.currency_id
        prec = currency.decimal_places
        doc_ecf = inv.doc_type_E(inv)
        is_e46 = doc_ecf == 'E46'

        summary = {
            'base_18': 0.0,
            'itbis_18': 0.0,
            'base_16': 0.0,
            'itbis_16': 0.0,
            'base_0': 0.0,
            'itbis_0': 0.0,
            'exento': 0.0,
            'monto_no_facturable': 0.0,
            'total_itbis': 0.0,
            'itbis_retenido': 0.0,
            'isr_retenido': 0.0,
            'impuestos_adicionales': [],
        }
        # Propina Legal e-CF: XSD ``TipoImpuesto`` 001 si el grupo lleva «Propina»
        # en el nombre (no hace falta ``tipo_impuesto_dgii`` en el maestro si el grupo coincide).
        propina_additional = {}

        is_refund = inv.move_type in ('out_refund', 'in_refund')
        # Solo ítems de producto/servicio (no secciones ni notas de línea).
        for line in inv.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')):
            if not line.tax_ids:
                continue
            nf_line = any(getattr(t, 'tipo_impuesto_dgii', None) == '4' for t in line.tax_ids)
            price_unit_disc = line.price_unit * (1.0 - (line.discount or 0.0) / 100.0)
            com_all = line.tax_ids.compute_all(
                price_unit_disc,
                currency=currency,
                quantity=line.quantity,
                product=line.product_id,
                partner=line.move_id.partner_id,
                is_refund=is_refund,
            )
            for tax in com_all.get('taxes', []):
                tax_id = inv.env['account.tax'].browse(tax['id'])
                tg = (tax_id.tax_group_id.name or '') if tax_id.tax_group_id else ''
                tg_u = tg.upper()
                base = float(tax.get('base') or 0.0)
                amt = float(tax.get('amount') or 0.0)

                if not amt and not is_e46:
                    if nf_line:
                        continue
                    summary['exento'] += base
                    continue

                if tax_id.amount < 0:
                    if 'ITBIS' in tg_u:
                        summary['itbis_retenido'] += abs(amt)
                    elif 'ISR' in tg_u or 'RETENCION' in tg_u:
                        summary['isr_retenido'] += abs(amt)
                    continue

                if abs(float(tax_id.amount) - 1.8) < 1e-9 and 'ITBIS' in tg_u:
                    summary['itbis_18'] += amt
                    base_18_normal = amt / 0.18 if abs(amt) > 1e-12 else 0.0
                    monto_exento_18 = base - base_18_normal
                    summary['base_18'] += base_18_normal
                    if monto_exento_18 > 0:
                        summary['exento'] += monto_exento_18
                    continue

                if tax_id.amount == 18 and 'ITBIS' in tg_u:
                    summary['base_18'] += base
                    summary['itbis_18'] += amt
                elif tax_id.amount == 16 and 'ITBIS' in tg_u:
                    summary['base_16'] += base
                    summary['itbis_16'] += amt
                elif tax_id.amount == 0 and is_e46 and 'ITBIS' in tg_u:
                    summary['base_0'] += base
                    summary['itbis_0'] += amt
                elif 'PROPINA' in tg_u and float(tax_id.amount or 0) >= 0:
                    rk = '%.10g' % float_round(float(tax_id.amount or 0.0), precision_digits=6)
                    if rk not in propina_additional:
                        propina_additional[rk] = {
                            'tasa': float(tax_id.amount or 0.0),
                            'monto': 0.0,
                        }
                    propina_additional[rk]['monto'] += float(amt)

            if nf_line:
                summary['monto_no_facturable'] += float_round(
                    line.price_subtotal or 0.0,
                    precision_digits=prec,
                )

        summary['itbis_retenido'] += float(getattr(inv, 'withholded_itbis', 0.0) or 0.0)
        summary['isr_retenido'] += float(getattr(inv, 'income_withholding', 0.0) or 0.0)

        summary['total_itbis'] = summary['itbis_18'] + summary['itbis_16'] + summary['itbis_0']

        for rk in sorted(propina_additional.keys(), key=lambda k: propina_additional[k]['tasa']):
            pdata = propina_additional[rk]
            rm = float_round(pdata['monto'], precision_digits=prec)
            if float_is_zero(rm, precision_rounding=prec):
                continue
            summary['impuestos_adicionales'].append({
                'tipo': '001',
                'tasa': pdata['tasa'],
                'monto': rm,
                'otros_impuestos': rm,
            })

        for key in (
            'base_18', 'itbis_18', 'base_16', 'itbis_16', 'base_0', 'itbis_0',
            'exento', 'monto_no_facturable', 'total_itbis', 'itbis_retenido', 'isr_retenido',
        ):
            summary[key] = float_round(summary[key], precision_digits=prec)

        gravado = summary['base_18'] + summary['base_16'] + summary['base_0']
        untaxed = float_round(inv.amount_untaxed or 0.0, precision_digits=prec)
        if float_round(
            gravado + summary['exento'] + summary['monto_no_facturable'],
            precision_digits=prec,
        ) != untaxed:
            _logger.warning(
                'DGII tax_summary: gravado+exento+monto_no_facturable (%s) != amount_untaxed (%s) en %s',
                gravado + summary['exento'] + summary['monto_no_facturable'],
                untaxed,
                inv.display_name,
            )

        amt_tax = float_round(inv.amount_tax or 0.0, precision_digits=prec)
        if summary['total_itbis'] != amt_tax:
            # amount_tax puede incluir impuestos no-ITBIS o retenciones en asiento; no es error duro
            _logger.info(
                'DGII tax_summary: total_itbis (%s) vs move.amount_tax (%s) en %s — revisar si aplica.',
                summary['total_itbis'],
                amt_tax,
                inv.display_name,
            )

        return summary

    def _prepare_invoice_data_for_api(self, invoice):
        """Prepare comprehensive invoice data for API with robust error handling"""
        _logger.info("Preparing invoice data for API - Invoice ID: %s, Document Number: %s", invoice.id, invoice.l10n_latam_document_number)
        try:
            # Prepare partner data with comprehensive fallback
            _logger.debug("Preparing partner data for invoice %s", invoice.id)
            partner_data = {
                'name': invoice.partner_id.name or '',
                'vat': ''.join(filter(str.isdigit, invoice.partner_id.vat or '')),
                'vat_full': (invoice.partner_id.vat or '').strip(),
                'street': invoice.partner_id.street or '',
                'state_name': invoice.partner_id.state_id.name if invoice.partner_id.state_id else '',
                'country_name': invoice.partner_id.country_id.name if invoice.partner_id.country_id else '',
                'country_code': invoice.partner_id.country_id.code
                if invoice.partner_id.country_id
                else '',
                'email': invoice.partner_id.email or '',
            }
            _logger.debug("Partner data prepared: %s", json.dumps(partner_data, default=str)[:200] + "..." if len(json.dumps(partner_data, default=str)) > 200 else json.dumps(partner_data, default=str))
            
            if hasattr(invoice.partner_id, 'l10n_do_dgii_tax_payer_type'):
                partner_data['l10n_do_dgii_tax_payer_type'] = (
                    invoice.partner_id.l10n_do_dgii_tax_payer_type or ''
                )
            p_geo = invoice._dgii_geo_codes_for_partner(invoice.partner_id)
            if p_geo.get('dgii_municipio_code'):
                partner_data['dgii_municipio_code'] = p_geo['dgii_municipio_code']
            if p_geo.get('dgii_provincia_code'):
                partner_data['dgii_provincia_code'] = p_geo['dgii_provincia_code']

            # Prepare currency data
            _logger.debug("Preparing currency data for invoice %s", invoice.id)
            currency_data = {
                'id': invoice.currency_id.id,
                'name': invoice.currency_id.name or '',
                'decimal_places': invoice.currency_id.decimal_places or 2,
                'inverse_rate': invoice._get_fiscal_rate()
            }
            _logger.debug("Currency data prepared: %s", json.dumps(currency_data, default=str))

            # Datos de compañía para API (sin campos legacy opcionales: companyLicCod, branchCod, posCod)
            _logger.debug("Preparing company data for invoice %s", invoice.id)
            c_partner = invoice.company_id.partner_id
            company_data = {
                'id': invoice.company_id.id,
                'name': invoice.company_id.name or '',
                'vat': ''.join(filter(str.isdigit, invoice.company_id.vat or '')),
                'street': (invoice.company_id.street or (c_partner.street if c_partner else '') or ''),
                'city': (c_partner.city if c_partner else '') or (invoice.company_id.city or ''),
            }
            _logger.debug("Basic company data prepared: %s", json.dumps(company_data, default=str))
            
            if c_partner:
                company_data['partner_id'] = {
                    'name': c_partner.name or '',
                    'commercial_partner_id': {
                        'name': (c_partner.commercial_partner_id.name or c_partner.name or ''),
                    },
                }
                em_geo = invoice._dgii_geo_codes_for_partner(c_partner)
                if em_geo.get('dgii_municipio_code'):
                    company_data['dgii_municipio_code'] = em_geo['dgii_municipio_code']
                if em_geo.get('dgii_provincia_code'):
                    company_data['dgii_provincia_code'] = em_geo['dgii_provincia_code']
                    
            # Log company DGII credentials information
            if hasattr(invoice.company_id, 'fe_dgii_id') and invoice.company_id.fe_dgii_id:
                fe = invoice.company_id.fe_dgii_id.filtered(lambda r: r.active)[:1] or invoice.company_id.fe_dgii_id[:1]
                _logger.info("Company DGII credentials found - ID: %s, Name: %s, RNC: %s, Environment: %s, Client Mode: %s", 
                            fe.id if fe else 'N/A', 
                            fe.name if fe else 'N/A', 
                            fe.rnc if fe else 'N/A',
                            getattr(fe, 'dgii_environment', 'N/A') if fe else 'N/A',
                            getattr(fe, 'dgii_client_mode', 'N/A') if fe else 'N/A')
                company_data['fe_dgii_id'] = [{
                    'id': fe.id,
                    'name': fe.name or invoice.company_id.name or '',
                    'rnc': fe.rnc or '',
                    'dgii_environment': fe.dgii_environment,
                    'dgii_client_mode': fe.dgii_client_mode,
                }]
            else:
                _logger.warning("No DGII credentials found for company %s", invoice.company_id.name)

            # Solo ``display_type == 'product'``: secciones y notas no van al JSON/XML e-CF.
            # Líneas API/DGII: siempre base sin impuesto + impuestos aparte (Odoo ya usa
            # price_subtotal=total_excluded, price_total=total_included; da igual si el
            # impuesto es price_include en el maestro).
            _logger.debug("Preparing invoice lines data for invoice %s", invoice.id)
            lines_data = []
            product_lines = invoice.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note'))
)
            _logger.info("Found %d product lines in invoice %s", len(product_lines), invoice.id)
            
            for line in product_lines:
                line_taxes = []
                for tax in self._dgii_effective_line_taxes(line):
                    tg_name = (tax.tax_group_id.name or '') if tax.tax_group_id else ''
                    tax_data = {
                        'name': tax.name or '',
                        'amount': tax.amount or 0.0,
                        'price_include': tax.price_include or False,
                        'tax_group_id': tax.tax_group_id.id if tax.tax_group_id else False,
                        'tax_group_name': tg_name,
                    }
                    tipo_dgii = getattr(tax, 'tipo_impuesto_dgii', None)
                    if tipo_dgii not in (None, False, ''):
                        tax_data['tipo_impuesto_dgii'] = tipo_dgii
                        if 'ITBIS' in tg_name.upper():
                            tax_data['tipo_impuesto_dgii_itbis'] = tipo_dgii
                    cod_tabla = getattr(tax, 'dgii_codigo_tabla_impuesto', None)
                    if cod_tabla not in (None, False, ''):
                        tax_data['dgii_codigo_tabla_impuesto'] = str(cod_tabla).strip()
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

                line_data = {
                    'name': self.get_clean_description(line),
                    'quantity': line.quantity or 0.0,
                    'discount': line.discount or 0.0,
                    'price_unit': adjusted_price_unit,
                    'price_subtotal': line.price_subtotal or 0.0,
                    'price_total': line.price_total or 0.0,
                    'tax_ids': line_taxes,
                    'product_code': line.product_id.default_code or '',
                    'product_id': {
                        'name': line.product_id.name or '',
                        'default_code': line.product_id.default_code or False,
                        'detailed_type': getattr(line.product_id,'detailed_type',line.product_id.type) or False,
                    },
                    **(
                        {'dgii_indicador_facturacion': line.dgii_indicador_facturacion}
                        if getattr(line, 'dgii_indicador_facturacion', False)
                        else {}
                    ),
                }
                lines_data.append(line_data)
                
            _logger.debug("Prepared %d lines data for invoice %s", len(lines_data), invoice.id)

            # Determine NCF expiration date with robust handling for all invoice types
            _logger.debug("Determining NCF expiration date for invoice %s", invoice.id)
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
            _logger.debug("Calculating ECF modification code for invoice %s", invoice.id)
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
            _logger.debug("Computing origin NCF date for invoice %s", invoice.id)
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

            _logger.debug("Preparing payments list for invoice %s", invoice.id)
            payments_list = invoice._prepare_payments_list_for_dgii_api(invoice)
            tipo_pago_dgii = invoice._dgii_tipo_pago_from_invoice(invoice)

            # Prepare main invoice record data
            _logger.debug("Preparing main record data for invoice %s", invoice.id)
            record_data = {
                'invoice_date': invoice.invoice_date.strftime('%Y-%m-%d') if invoice.invoice_date else '',
                'l10n_latam_document_number': invoice.l10n_latam_document_number or '',
                'l10n_do_ecf_security_code': (invoice.l10n_do_ecf_security_code or '').strip() or None,
                # Siempre 0: e-CF en base gravable + ITBIS por separado (no precio con ITBIS incluido).
                'indicador_monto_gravado': 0,
                'ncf_expiration_date': ncf_expiration_date,
                'l10n_do_origin_ncf': l10n_do_origin_ncf,
                'l10n_do_origin_ncf_date': l10n_do_origin_ncf_date,
                'l10n_do_income_type': invoice.l10n_do_income_type,
                'l10n_do_ecf_modification_code': ecf_modification_code,
                'l10n_do_tipo_pago': tipo_pago_dgii,
                'partner_id': partner_data,
                'currency_id': currency_data,
                'company_id': company_data,
                'invoice_payments_widget': getattr(invoice,'invoice_payments_widget',False),
                'reversed_entry_id': invoice.reversed_entry_id.id if invoice.reversed_entry_id else None,
                'debit_origin_id': getattr(invoice,'debit_origin_id',False).id if getattr(invoice, 'debit_origin_id', False) else None,
                'lines': lines_data,
                'amount_total': float(invoice.amount_total or 0.0),
                'amount_untaxed': float(invoice.amount_untaxed or 0.0),
                'amount_tax': float(invoice.amount_tax or 0.0),
                'withholded_itbis': float(getattr(invoice, 'withholded_itbis', 0.0) or 0.0),
                'income_withholding': float(getattr(invoice, 'income_withholding', 0.0) or 0.0),
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
            _logger.debug("Cleaning dates in record data for invoice %s", invoice.id)
            record_data_clean = clean_dates(record_data)
            lines_data_clean = clean_dates(lines_data)
            record_data_clean['lines'] = lines_data_clean
            payments_clean = clean_dates(payments_list)
            tax_summary = invoice._prepare_tax_summary_for_dgii_api(invoice)
            tax_summary = clean_dates(tax_summary)
            _logger.error("API DATA: %s", json.dumps(record_data_clean, indent=2, default=str))
            
            _logger.info("Invoice data preparation completed successfully for invoice %s", invoice.id)
            return {
                'record': record_data_clean,
                'lines': lines_data_clean,
                'payments': payments_clean,
                'tax_summary': tax_summary,
                'amount_total': float(invoice.amount_total or 0.0),
                'amount_untaxed': float(invoice.amount_untaxed or 0.0),
                'amount_tax': float(invoice.amount_tax or 0.0),
            }

        except Exception as e:
            _logger.error(f"Error preparing invoice data for API: {str(e)}")
            _logger.error("Error details for invoice %s - Type: %s, Args: %s", invoice.id, type(e).__name__, str(e.args))
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
            _logger.info(json.dumps(invoice_data, indent=2, default=str))
            
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
            _logger.info("API Request Data: %s", json.dumps(api_data, indent=2, default=str))
            
            response = self._call_dgii_api('/dgii/v1/generate_xml', api_data)
            
            # JSON-RPC: cuerpo útil en result; errores de red/rpc arriba en response['error']
            if response.get('error'):
                rpc_err = response['error']
                if isinstance(rpc_err, dict):
                    rpc_err = rpc_err.get('message') or rpc_err.get('data') or str(rpc_err)
                _logger.error("XML Generation JSON-RPC error: %s", rpc_err)
                raise UserError(_('XML Generation (RPC): %s') % rpc_err)

            res = response.get('result') or {}
            _logger.info("DGII API result keys: %s", list(res.keys()))
            if res.get('error') or res.get('success') is False:
                api_err = res.get('error') or _('La API devolvió error sin mensaje')
                _logger.error("XML Generation API Error: %s", api_err)
                raise UserError(_('XML Generation Error: %s') % api_err)

            # Compat: respuestas sin 'success' explícito pero con xml_content
            xml_content = res.get('xml_content') or ''
            xml_name = res.get('xml_name', f'{type_document}_{invoice.l10n_latam_document_number}.xml')

            # Additional validation of XML content
            if not xml_content:
                _logger.error("No XML content generated for invoice %s", invoice.id)
                _logger.error("Full API Response: %s", json.dumps(response, indent=2, default=str))
                raise UserError(_('No XML data was generated for the invoice. Please check the invoice details and API configuration.'))
            
            _logger.info("XML Generation Successful. XML Name: %s", xml_name)
            _logger.info("XML Content Length: %d characters", len(xml_content))
            
            return xml_content, xml_name
            
        except UserError:
            raise
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
        Tipo e-CF (E31–E47) para API DGII, solo desde prefijo **E##** en tipo LATAM o e-NCF.

        No hay conversión desde serie B, códigos cortos (FF/FC/…) ni `move_type` genérico:
        cada localización debe asignar e-NCF/tipo con prefijo electrónico.
        """
        import re
        doc_type = None

        latam_dt = getattr(invoice, 'l10n_latam_document_type_id', None)
        if latam_dt and getattr(latam_dt, 'doc_code_prefix', None):
            prefix = (latam_dt.doc_code_prefix or '').strip()
            ecf_from_type = re.match(r'^(E\d{2})', prefix, re.IGNORECASE)
            if ecf_from_type:
                doc_type = ecf_from_type.group(1).upper()

        if doc_type is None and invoice.l10n_latam_document_number:
            _logger.info("EX347 0 Latam Document %s", invoice.l10n_latam_document_number)
            ncf_match = re.match(r'^(E\d{2})', invoice.l10n_latam_document_number, re.I)
            if ncf_match:
                doc_type = ncf_match.group(1).upper()
                _logger.info("EX347 1 e-CF desde NCF: %s", doc_type)

        if doc_type:
            if doc_type not in self._VALID_ECF_API_TYPES:
                raise UserError(
                    _('Tipo e-CF %s no está en el catálogo API (E31, E32, E33, E34, E41, E43–E47).')
                    % doc_type
                )
            return doc_type

        raise UserError(
            _('No se pudo determinar el tipo e-CF (E31–E47). '
              'Defina un tipo de documento o e-NCF con prefijo E## (p. ej. E320000000001). '
              '(Factura %(inv)s).')
            % {'inv': invoice.display_name or invoice.id}
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
            _logger.info("EX444 0 doctype rebuild %s", doc_type)
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

    dgii_indicador_facturacion = fields.Selection(
        selection=[
            ('0', '0 — No facturable'),
            ('1', '1 — Gravado (ITBIS 1 — 18%)'),
            ('2', '2 — Gravado (ITBIS 2 — 16%)'),
            ('3', '3 — Gravado (ITBIS 3 — 0%)'),
            ('4', '4 — Monto exento'),
        ],
        string='Indicador facturación DGII',
        help=(
            'Valor XSD IndicadorFacturacion (0–4) en la línea del e-CF. No es el mismo código '
            'que tipo_impuesto_dgii del impuesto (0–6). Equivalencias: README l10n_do_dgii_fe_base '
            '«Equivalencias DGII». Vacío: el generador deduce desde impuestos (monto ≥ 0); las '
            'retenciones negativas no clasifican — use este campo sólo si debe forzar el indicador.'
        ),
    )

    @api.constrains('tax_ids')
    def _check_single_tax_per_group_dgii(self):
        """Ensure only one tax per tax_group_id is applied to invoice lines for DGII."""
        for line in self:
            # Only validate for DGII journals and when invoice is posted or being posted
            if (line.tax_ids and line.move_id and line.move_id.journal_id.is_dgii and
                line.move_id.state in ['posted', 'draft'] and line.display_type not in ('line_section', 'line_note'):
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
    #                     _(
    #                         "You cannot validate and invoice of Fiscal Type "
    #                         "Regímen Especial with ITBIS/ISC.\n\n"
    #                         "See DGII General Norm 05-19, Art. 3 for further "
    #                         "information"
    #                     )
    #                 )
