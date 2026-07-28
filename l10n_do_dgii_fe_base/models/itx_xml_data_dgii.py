from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import requests
import logging
import base64
import json
import re
from datetime import datetime, date
from urllib.parse import unquote
#from odoo.addons.l10n_do_dgii_fe_base.utils.xml_base import XmlInterface

_logger = logging.getLogger(__name__)

# ir.config_parameter: si es true, si la API no envía qr_* se intenta armar solo RFCE (ConsultaTimbreFC) en Odoo.
# Si es false, el QR solo viene del API (recomendado para un solo sitio de mantenimiento: el servicio DGII).
ICP_QR_LOCAL_FALLBACK = 'l10n_do_dgii_fe_base.qr_local_fallback'
# Parámetros del sistema: log extra para PDF / sello (mismas claves que en account.move).
ICP_DEBUG_REPORT_QR = 'l10n_do_dgii_fe_base.debug_report_qr'


def dgii_security_code_from_signed_xml_string(signed_xml):
    """Ver mismo nombre en ``itx_dgii_api.models.dgii_signer`` (RFCE: CodigoSeguridadeCF; ECF: SignatureValue)."""
    if not signed_xml or not isinstance(signed_xml, str):
        return ''
    chunk = signed_xml.strip()[:800000]
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(chunk)
    except ET.ParseError:
        return ''

    def _local_tag(el):
        if el.tag is None:
            return ''
        return el.tag.split('}')[-1]

    for el in root.iter():
        if _local_tag(el) == 'CodigoSeguridadeCF':
            txt = (el.text or '').strip()
            if txt:
                return txt[:6]

    sig_val = ''
    for el in root.iter():
        if _local_tag(el) == 'SignatureValue' and (el.text or '').strip():
            sig_val = ''.join((el.text or '').split())
            break
    if len(sig_val) >= 6:
        return sig_val[:6]

    for el in root.iter():
        if _local_tag(el) == 'DigestValue' and (el.text or '').strip():
            d = ''.join((el.text or '').split())
            if len(d) >= 6:
                return d[:6]
            break
    return ''


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


def _dgii_format_mensajes_items(mensajes):
    """Normaliza ``mensajes`` DGII (lista o dict) a textos para UI."""
    if isinstance(mensajes, dict):
        mensajes = [mensajes]
    if not isinstance(mensajes, (list, tuple)):
        return []
    out = []
    for m in mensajes:
        if isinstance(m, dict):
            cod = m.get('codigo', m.get('Codigo', m.get('code')))
            val = (
                m.get('valor') or m.get('Valor') or m.get('value')
                or m.get('mensaje') or m.get('Mensaje')
            )
            if val is not None and str(val).strip():
                if cod is not None and str(cod) != '':
                    out.append('%s: %s' % (cod, val))
                else:
                    out.append(str(val))
            elif cod is not None:
                out.append(str(cod))
        elif m is not None and str(m).strip():
            out.append(str(m))
    return out


def _dgii_recepcion_dict_from_data(data):
    if not isinstance(data, dict):
        return None
    for key in ('dgii_recepcion', 'response', 'dgii_response', 'recepcion'):
        rec = data.get(key)
        if isinstance(rec, dict):
            return rec
    if any(
        data.get(k) is not None
        for k in ('mensajes', 'messages', 'Mensajes', 'estado', 'Estado', 'codigo', 'Codigo')
    ):
        return data
    nested = data.get('result')
    if isinstance(nested, dict):
        return _dgii_recepcion_dict_from_data(nested)
    return None


def _dgii_parse_json_dict_from_text(blob):
    if not isinstance(blob, str) or '{' not in blob:
        return None
    idx = blob.find('{')
    try:
        parsed = json.loads(blob[idx:])
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def dgii_mensajes_text_from_response_data(response_data):
    """Texto legible desde ``mensajes[].valor`` (p. ej. código 1381 RNCComprador)."""
    if not isinstance(response_data, dict):
        return ''
    rec = _dgii_recepcion_dict_from_data(response_data)
    msgs = []
    if rec:
        msgs = _dgii_format_mensajes_items(
            rec.get('mensajes') or rec.get('messages') or rec.get('Mensajes')
        )
    if not msgs:
        msgs = _dgii_format_mensajes_items(
            response_data.get('mensajes')
            or response_data.get('messages')
            or response_data.get('Mensajes')
        )
    if not msgs:
        for key in ('error', 'message'):
            parsed = _dgii_parse_json_dict_from_text(response_data.get(key))
            if not parsed:
                continue
            inner = _dgii_recepcion_dict_from_data(parsed) or parsed
            msgs = _dgii_format_mensajes_items(
                inner.get('mensajes') or inner.get('messages') or inner.get('Mensajes')
            )
            if msgs:
                break
    return ' | '.join(msgs) if msgs else ''


# Estados de transporte API (no son etiquetas DGII para UI).
_DGII_API_TRANSPORT_STATUSES = frozenset({
    'ACCEPTED', 'PENDING', 'CHECKED', 'APPROVED', 'REJECTED', 'PROCESSED',
    'SUBMISSION_ERROR', 'AUTH_ERROR', 'NETWORK_ERROR', 'INVALID_RESPONSE',
    'ERROR',
})


def dgii_estado_label_from_response(response_data):
    """
    Etiqueta DGII para UI: prevalece ``dgii_status`` del API si es estado real
    (p. ej. «Aceptado Condicional»), no ``status`` técnico (ACCEPTED/PENDING).
    """
    if not isinstance(response_data, dict):
        return ''
    for key in ('dgii_status', 'dgii_estado'):
        val = response_data.get(key)
        if val is None:
            continue
        sval = str(val).strip()
        if sval and sval.upper() not in _DGII_API_TRANSPORT_STATUSES:
            return sval
    rec = _dgii_recepcion_dict_from_data(response_data) or {}
    for key in ('estado', 'Estado'):
        val = rec.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ''


def dgii_estado_classification(label):
    """Clasifica estado DGII: approved | conditional | rejected | pending | unknown."""
    key = (label or '').replace(' ', '').lower()
    if key and 'rechazado' in key and 'condicional' not in key:
        return 'rejected'
    if key and 'aceptado' in key and 'condicional' in key:
        return 'conditional'
    if key in ('aceptado', 'autorizado') or (key and 'autorizado' in key):
        return 'approved'
    if key and ('proceso' in key or 'pendiente' in key):
        return 'pending'
    return 'unknown'


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
        (
            'error_no_enviado',
            'No aceptado por DGII / validación (reintentar)',
        ),
        ('error', 'Error técnico (API, red, firma, etc.)'),
        ('procesed', 'Procesado'),
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

    # Respuesta DGII / API (contrato actual: recepción + consulta + auditoría JSON).
    # Totales, RNC, eNCF, líneas: en account.move / xml_data / signed_xml — no duplicar aquí.
    authorized = fields.Boolean(
        string='Autorizado',
        help='True si DGII aceptó o autorizó el comprobante.',
    )
    auth_date = fields.Date(
        string='Fecha de Autorización',
        help='Fecha de autorización cuando la devuelve check_status (p. ej. mock).',
    )
    qr_code = fields.Char(
        string='QR Code',
        help='Sello/url para código QR en PDF (desde API qr_code o fallback RFCE).',
    )
    dgi_err_msg = fields.Text(string='Mensaje de Error DGI')
    dgi_status = fields.Char(string='Estado DGI (Texto)', default='NO ENVIADO')
    json_response_sent = fields.Text(string='Res JSON(envio)')
    json_response = fields.Text(string='Res JSON(recibido)')

    track_id = fields.Char(
        string='Track ID (DGII)',
        help='Tracking ID returned by DGII for status verification',
        index=True,
    )
    signature = fields.Char(
        string='Código de Seguridad',
        help='6-character security code from signed XML',
        size=6,
    )
    signed_xml = fields.Text(
        string='XML Firmado',
        help='The digitally signed XML document',
    )
    dgii_auth_number = fields.Char(
        string='Número de Autorización DGII',
        help='numeroAutorizacion / auth_number devuelto por DGII o la API.',
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
        elif isinstance(data, (bytes, bytearray)):
            # p. ej. Binary fields de read(); evita fallo JSON en payloads API
            return base64.b64encode(bytes(data)).decode('ascii')
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

    def _sync_signature_from_signed_xml_if_missing(self):
        """Si la API dejó ``signature`` vacío (ECF sin CodigoSeguridadeCF), derivarlo del XML firmado."""
        self.ensure_one()
        if (self.signature or '').strip():
            return
        sx = (self.signed_xml or '').strip()
        if not sx:
            return
        code = dgii_security_code_from_signed_xml_string(sx)
        if code:
            self.signature = code

    @staticmethod
    def _dgii_qr_fechafirma_param(fechafirma):
        """DGII RI: ``dd-mm-aaaa HH:mm:ss`` con espacio como ``%20`` (no ``+`` / ``%2B``)."""
        return (fechafirma or '').strip().replace(' ', '%20')

    @staticmethod
    def _dgii_qr_monto_param(monto):
        try:
            return '%.2f' % abs(float(monto))
        except (TypeError, ValueError):
            return '0.00'

    def _parse_xml_text_tag(self, tag, xml_text=None):
        """Primer valor textual de ``<Tag>...</Tag>`` en XML firmado."""
        chunk = xml_text if xml_text is not None else (self.signed_xml or '')
        if not chunk:
            return ''
        m = re.search(r'<' + re.escape(tag) + r'>([^<]+)</' + re.escape(tag) + r'>', chunk)
        return m.group(1).strip() if m else ''

    def _dgii_qr_monto_from_signed_xml(self, inv=None):
        """``montototal`` del QR = ``MontoTotal`` del e-CF firmado (DOP), no ``amount_total`` USD."""
        self.ensure_one()
        monto_xml = self._parse_xml_text_tag('MontoTotal')
        if monto_xml:
            return self._dgii_qr_monto_param(monto_xml)
        inv = inv or self.account_move_id
        if inv and hasattr(inv, '_dgii_amount_total_in_dop'):
            return self._dgii_qr_monto_param(inv._dgii_amount_total_in_dop())
        if inv:
            return self._dgii_qr_monto_param(inv.amount_total)
        return '0.00'

    def _normalize_dgii_qr_canonical_url(self, raw):
        """Normaliza ``fechafirma`` / ``FechaFirma`` y ``encf`` en URL cruda (API o legacy)."""
        s = str(raw or '').strip()
        if not s:
            return s
        for param in ('fechafirma', 'FechaFirma'):
            m = re.search(r'(' + param + r'=)([^&]+)', s, re.I)
            if not m:
                continue
            val = unquote(m.group(2).replace('+', ' '))
            if re.match(r'\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}', val):
                fixed = val.replace(' ', '%20')
                s = s[:m.start(2)] + fixed + s[m.end(2):]
            break
        for param in ('encf', 'ENCF'):
            m = re.search(r'(' + param + r'=)([^&]+)', s, re.I)
            if m:
                s = s[:m.start(2)] + m.group(2).upper() + s[m.end(2):]
                break
        return s

    def _build_fc_consulta_timbre_qr_stamp(self):
        """
        Sello para QR en RFCE: ConsultaTimbreFC (misma URL base que l10n_do_ecf_invoicing).
        """
        self.ensure_one()

        inv = self.account_move_id
        sec = (self.signature or '').strip()
        if not inv or not sec:
            return None
        hdr = (self.signed_xml or '')[:1200]
        if '<RFCE>' not in hdr:
            return None
        cre = self.company_id.fe_dgii_id.filtered(lambda p: p.active)[:1]
        env_name = (cre.dgii_environment or 'CerteCF').strip()
        rnc = str(inv.company_id.vat or '').strip()
        encf = (inv.l10n_latam_document_number or inv.ref or '').strip()
        if not rnc or not encf:
            return None
        monto_s = self._dgii_qr_monto_from_signed_xml(inv)
        return (
            'https://fc.dgii.gov.do/%s/ConsultaTimbreFC?RncEmisor=%s&ENCF=%s&MontoTotal=%s&CodigoSeguridad=%s'
            % (env_name, rnc, encf.upper(), monto_s, sec)
        )

    def _build_ecf_consulta_timbre_qr_stamp(self):
        """
        Sello QR para e-CF completo (no RFCE): ``https://ecf.dgii.gov.do/{ambiente}/consultatimbre``.
        Parámetros según descripción técnica DGII (RI / consulta timbre).
        """
        self.ensure_one()

        inv = self.account_move_id
        sec = (self.signature or '').strip()
        if not inv or not sec:
            return None
        hdr = (self.signed_xml or '')[:1200]
        if '<ECF>' not in hdr:
            return None
        cre = self.company_id.fe_dgii_id.filtered(lambda p: p.active)[:1]
        env_seg = (cre.dgii_environment or 'certecf').strip().lower()
        rnc_e = ''.join(c for c in str(inv.company_id.vat or '') if c.isdigit())
        rnc_c = ''.join(c for c in str(inv.partner_id.vat or '') if c.isdigit())
        encf = (inv.l10n_latam_document_number or inv.ref or '').strip()
        if not rnc_e or not encf:
            return None
        fecha_emision = self._parse_xml_text_tag('FechaEmision') or (
            inv.invoice_date.strftime('%d-%m-%Y') if inv.invoice_date else ''
        )
        if not fecha_emision:
            return None
        monto_s = self._dgii_qr_monto_from_signed_xml(inv)
        dt_firma = self._parse_fecha_hora_firma_from_xml(self.signed_xml or '')
        if dt_firma:
            fechafirma = dt_firma.strftime('%d-%m-%Y %H:%M:%S')
        elif inv.l10n_do_ecf_sign_date:
            try:
                dt2 = fields.Datetime.to_datetime(inv.l10n_do_ecf_sign_date)
                fechafirma = dt2.strftime('%d-%m-%Y %H:%M:%S')
            except (ValueError, TypeError, AttributeError):
                fechafirma = ''
        else:
            fechafirma = ''
        if not fechafirma:
            return None
        fechafirma_param = self._dgii_qr_fechafirma_param(fechafirma)
        return (
            'https://ecf.dgii.gov.do/%s/consultatimbre?rncemisor=%s&rnccomprador=%s&encf=%s'
            '&fechaemision=%s&montototal=%s&fechafirma=%s&codigoseguridad=%s'
            % (
                env_seg,
                rnc_e,
                rnc_c,
                encf.upper(),
                fecha_emision,
                monto_s,
                fechafirma_param,
                sec,
            )
        )

    def _parse_dgii_datetime_loose(self, raw):
        """Parsea fechas típicas DGII / API (string o datetime)."""
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw
        s = str(raw).strip()
        if not s:
            return None
        if s.endswith('Z'):
            s = s[:-1]
        if len(s) > 19 and s[19] in '+-':
            s = s[:19]
        fmts = (
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%d-%m-%Y %H:%M:%S',
        )
        for fmt in fmts:
            try:
                return datetime.strptime(s[:19], fmt)
            except ValueError:
                continue
        try:
            dt = fields.Datetime.to_datetime(s)
            if isinstance(dt, datetime):
                return dt
        except Exception:
            pass
        return None

    def _parse_fecha_hora_firma_from_xml(self, xml_text):
        if not xml_text or not isinstance(xml_text, str):
            return None
        chunk = xml_text[:20000]
        m = re.search(r'FechaHoraFirma[^>]*>([^<]+)<', chunk)
        if not m:
            return None
        return self._parse_dgii_datetime_loose(m.group(1).strip())

    def _ecf_sign_datetime_from_submit_response(self, response_data):
        """Fecha/hora firma digital para ``account.move.l10n_do_ecf_sign_date``."""
        if not isinstance(response_data, dict):
            return None
        candidates = []
        for key in (
            'sign_date',
            'signDate',
            'fecha_firma',
            'fechaFirma',
            'fecha_hora_firma',
            'fechaHoraFirma',
            'FechaHoraFirma',
        ):
            v = response_data.get(key)
            if v:
                candidates.append(v)
        rec = response_data.get('dgii_recepcion')
        if isinstance(rec, dict):
            for key in ('fechaFirma', 'FechaHoraFirma', 'sign_date', 'signDate'):
                v = rec.get(key)
                if v:
                    candidates.append(v)
        res = response_data.get('result')
        if isinstance(res, dict):
            for key in ('signDate', 'sign_date', 'fechaFirma'):
                v = res.get(key)
                if v:
                    candidates.append(v)
        for raw in candidates:
            dt = self._parse_dgii_datetime_loose(raw)
            if dt:
                return dt
        sx = response_data.get('signed_xml') or self.signed_xml
        return self._parse_fecha_hora_firma_from_xml(sx or '')

    def _extract_qr_stamp_from_api_response(self, response_data):
        """Sello listo para QR: **fuente preferida = API** (un solo contrato para todos los clientes Odoo).

        Orden: raíz del JSON → ``dgii_recepcion`` → ``result``. Primera clave con valor no vacío.
        Claves habituales (ampliar solo del lado API si hace falta; evita ramas por versión en Odoo).
        """
        if not isinstance(response_data, dict):
            return ''
        root_keys = (
            'qr_code',
            'electronic_stamp',
            'qr_stamp',
            'stamp',
            'ecf_electronic_stamp',
            'qr_url',
            'stamp_qr',
            'sello_electronico',
        )
        nested_keys = (
            'qrCode',
            'qr_code',
            'electronicStamp',
            'electronic_stamp',
            'QR',
            'stamp',
        )

        def _first_str(*values):
            for val in values:
                if val is None or val is False:
                    continue
                s = str(val).strip()
                if s:
                    return s
            return ''

        chunks = []
        for key in root_keys:
            chunks.append(response_data.get(key))
        rec = response_data.get('dgii_recepcion')
        if isinstance(rec, dict):
            for key in nested_keys:
                chunks.append(rec.get(key))
        result = response_data.get('result')
        if isinstance(result, dict):
            for key in root_keys + nested_keys:
                chunks.append(result.get(key))

        return _first_str(*chunks)

    def _store_qr_code_normalized(self, raw_stamp):
        """Guarda ``qr_code`` en el mismo formato que espera ``/report/barcode`` (un nivel quote)."""
        self.ensure_one()
        if raw_stamp is None or raw_stamp is False:
            return False
        from odoo.tools import urls

        raw = self._normalize_dgii_qr_canonical_url(raw_stamp)
        if not raw:
            return False
        self.qr_code = urls.url_quote_plus(raw)
        return True

    def _dgii_debug_report_qr_enabled(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(ICP_DEBUG_REPORT_QR, 'False')
        return str(raw if raw is not None else 'False').lower() in (
            '1',
            'true',
            'yes',
            'on',
        )

    def _assign_qr_code_after_recepcion(self, response_data):
        """Tras recepción: 1) API 2) opcional fallback local RFCE (solo consumo)."""
        self.ensure_one()
        api_stamp = self._extract_qr_stamp_from_api_response(response_data)
        dbg = self._dgii_debug_report_qr_enabled()
        if dbg:
            top_keys = (
                list(response_data.keys())[:30]
                if isinstance(response_data, dict)
                else []
            )
            _logger.info(
                '[DGII][report_qr] recepcion -> asignar QR | itx_id=%s move_id=%s '
                'api_extract_non_empty=%s response_top_keys=%s',
                self.id,
                self.account_move_id.id if self.account_move_id else None,
                bool(api_stamp),
                top_keys,
            )
        if self._store_qr_code_normalized(api_stamp):
            if dbg:
                _logger.info(
                    '[DGII][report_qr] qr persistido desde API | itx_id=%s final_len=%s',
                    self.id,
                    len((self.qr_code or '').strip()),
                )
            return

        _fb_raw = self.env['ir.config_parameter'].sudo().get_param(ICP_QR_LOCAL_FALLBACK, 'True')
        fallback_on = str(_fb_raw if _fb_raw is not None else 'True').lower() in (
            '1',
            'true',
            'yes',
            'on',
        )
        if not fallback_on:
            _logger.info(
                '[DGII][report_qr] fallback local desactivado (%s), sin qr desde API | itx_id=%s',
                ICP_QR_LOCAL_FALLBACK,
                self.id,
            )
            return

        stamp = self._build_fc_consulta_timbre_qr_stamp()
        if stamp and self._store_qr_code_normalized(stamp):
            if dbg:
                _logger.info(
                    '[DGII][report_qr] qr persistido fallback RFCE FC | itx_id=%s final_len=%s',
                    self.id,
                    len((self.qr_code or '').strip()),
                )
            return

        stamp_ecf = self._build_ecf_consulta_timbre_qr_stamp()
        if stamp_ecf and self._store_qr_code_normalized(stamp_ecf):
            if dbg:
                _logger.info(
                    '[DGII][report_qr] qr persistido fallback ECF consultatimbre | itx_id=%s final_len=%s',
                    self.id,
                    len((self.qr_code or '').strip()),
                )
            return

        _logger.info(
            'QR: sin sello API y sin fallback FC/ECF aplicable (firma/código seguridad). id=%s',
            self.id,
        )

    def _apply_dgii_recepcion_from_submit(self, response_data):
        """
        Guarda la respuesta del POST de recepción en ``json_response`` y campos ``dgi_*``.
        RFCE a menudo no devuelve ``trackId``; sin esto la verificación nunca corre y el QR queda vacío.
        """
        self.ensure_one()
        if not isinstance(response_data, dict):
            return
        self._enrich_api_response_with_dgii_json_from_error(response_data)
        try:
            self.json_response = json.dumps(response_data, default=str)
        except (TypeError, ValueError):
            pass

        rec = _dgii_recepcion_dict_from_data(response_data) or {}

        dgii_label = dgii_estado_label_from_response(response_data)
        if not dgii_label:
            tid = response_data.get('track_id') or response_data.get('trackId')
            if tid and response_data.get('success'):
                dgii_label = _('Pendiente de verificación DGII')
            elif rec.get('estado') or rec.get('Estado'):
                dgii_label = str(rec.get('estado') or rec.get('Estado')).strip()

        estado_key = (dgii_label or '').replace(' ', '').lower()
        dgii_class = dgii_estado_classification(dgii_label)

        dgii_msgs = dgii_mensajes_text_from_response_data(response_data)
        if dgii_msgs:
            self.dgi_err_msg = dgii_msgs

        na = response_data.get('numero_autorizacion')
        if na:
            sna = str(na)
            self.dgii_auth_number = sna

        if dgii_class == 'rejected':
            self.status = 'error_no_enviado'
            self.dgi_status = dgii_label or 'Rechazado'
            self.authorized = False
        elif dgii_class == 'approved':
            self.dgi_status = dgii_label or 'Aceptado'
            self.status = 'procesed'
            self.authorized = True
        elif dgii_class == 'conditional':
            self.dgi_status = dgii_label or 'Aceptado Condicional'
            self.status = 'sent'
            self.authorized = False
        elif dgii_class == 'pending':
            self.dgi_status = dgii_label or _('Pendiente de verificación DGII')
            if self.status not in ('error', 'error_no_enviado', 'procesed'):
                self.status = 'sent'
            self.authorized = False
        elif dgii_label:
            self.dgi_status = dgii_label

        # QR: canónico en API; Odoo solo persiste (+ fallback RFCE opcional, ver _assign_qr_code_after_recepcion).
        self._assign_qr_code_after_recepcion(response_data)

        inv = self.account_move_id
        sign_dt = self._ecf_sign_datetime_from_submit_response(response_data)
        if inv and inv.is_ecf_invoice and getattr(inv.journal_id, 'is_dgii', False):
            invoice_updates = {}
            if self.signature:
                invoice_updates['l10n_do_ecf_security_code'] = self.signature
            if sign_dt:
                invoice_updates['l10n_do_ecf_sign_date'] = sign_dt
            if invoice_updates:
                inv.write(invoice_updates)
                _logger.info(
                    '[DGII][ecf_sign_date] invoice %s actualizada desde recepcion | campos=%s fecha=%s',
                    inv.id,
                    list(invoice_updates.keys()),
                    invoice_updates.get('l10n_do_ecf_sign_date'),
                )
            if not sign_dt:
                dbg = self._dgii_debug_report_qr_enabled()
                if dbg or self.signature or self.signed_xml or response_data.get('signed_xml'):
                    _logger.info(
                        '[DGII][ecf_sign_date] no resolv fecha firma tras submit | move_id=%s itx_id=%s '
                        'tiene_signature=%s signed_xml_len=%s sample_response_keys=%s',
                        inv.id,
                        self.id,
                        bool(self.signature),
                        len((self.signed_xml or '') or (response_data.get('signed_xml') or '') or ''),
                        list(response_data.keys())[:22] if isinstance(response_data, dict) else [],
                    )

    def _enrich_api_response_with_dgii_json_from_error(self, response_data):
        """Si la API mete el JSON de DGII solo dentro de ``error``/``message`` (HTTP≠200), exponerlo como ``dgii_recepcion``."""
        if not isinstance(response_data, dict) or response_data.get('dgii_recepcion'):
            return
        for key in ('error', 'message'):
            blob = response_data.get(key)
            if not blob or not isinstance(blob, str):
                continue
            idx = blob.find('{')
            if idx == -1:
                continue
            fragment = blob[idx:].strip()
            try:
                rec = json.loads(fragment)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if not isinstance(rec, dict):
                continue
            if (
                rec.get('mensajes') is not None
                or rec.get('estado')
                or rec.get('Estado')
                or rec.get('codigo') is not None
            ):
                response_data['dgii_recepcion'] = rec
                est = rec.get('estado') or rec.get('Estado')
                if est:
                    response_data.setdefault('dgii_estado', est)
                break

    def _is_recoverable_dgii_submission_rejection(self, response_data, final_msg):
        """
        Respuesta negativa tras intento de recepción en DGII (u otro error HTTP con cuerpo DGII).

        Incluye: estado Rechazado, código 2, mensajes de validación XML emitidos **por DGII**
        (p.ej. orden de nodos / «invalid child element»), y errores 4xx típicos cuando ya hay
        XML firmado en la respuesta.

        No elevar UserError: persistir en ``itx.xml.data.dgii`` (``dgi_status`` / ``dgi_err_msg``).

        No confundir con fallos previos al envío (firma, XML vacío, JSON mal formado): esos siguen
        como UserError si no entran aquí.
        """
        if not isinstance(response_data, dict):
            return False
        blob_msg = ' '.join(
            str(x or '')
            for x in (
                final_msg,
                response_data.get('error'),
                response_data.get('message'),
            )
        ).lower()

        rec = response_data.get('dgii_recepcion')
        if isinstance(rec, dict):
            est = str(rec.get('estado') or rec.get('Estado') or '').replace(' ', '').lower()
            if est and 'rechazado' in est and 'condicional' not in est:
                return True
            cod = rec.get('codigo')
            try:
                if int(cod) == 2:
                    return True
            except (TypeError, ValueError):
                if str(cod) == '2':
                    return True
            # DGII a veces solo devuelve error/mensaje textual (sin estado estándar)
            for key in ('error', 'mensaje', 'Mensaje'):
                frag = str(rec.get(key) or '').lower()
                if not frag:
                    continue
                if 'estructura del archivo xml' in frag:
                    return True
                if 'invalid child element' in frag:
                    return True
                if 'list of possible elements expected' in frag:
                    return True
        for key in ('dgii_estado', 'dgii_status'):
            val = response_data.get(key)
            if not val:
                continue
            v = str(val).replace(' ', '').lower()
            if 'rechazado' in v and 'condicional' not in v:
                return True
        if final_msg:
            compact = final_msg.replace(' ', '').lower()
            if '"estado":"rechazado"' in compact or "'estado':'rechazado'" in compact:
                return True
            if 'rechazado' in final_msg.lower() and 'dgii rejected' in final_msg.lower():
                return True
        # Texto típico cuando la API encapsula el JSON de DGII en ``error`` (HTTP≠200)
        if 'dgii rejected the submission' in blob_msg:
            return True
        if 'estructura del archivo xml' in blob_msg:
            return True
        if 'invalid child element' in blob_msg:
            return True
        if 'list of possible elements expected' in blob_msg:
            return True

        st = str(response_data.get('status') or '')
        if st == 'REJECTED':
            return True
        # p.ej. ERROR_400: hubo intento de recepción y cuerpo explicativo de DGII/gateway
        if st.startswith('ERROR_'):
            tail = st.split('_', 1)[-1]
            try:
                code = int(tail)
            except ValueError:
                code = None
            if code is not None and 400 <= code < 500 and response_data.get('signed_xml'):
                return True

        return False

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

        if cre._use_legacy_cert_in_request():
            if not cre.certificate_file or not cre.certificate_password:
                raise UserError(
                    _('Configure certificado y contraseña, o sincronice con la API.')
                )
        else:
            cre._require_synced_for_prod()

        if not cre.rnc:
            raise UserError(_('No hay RNC configurado en la compañía.'))

        # Tipo e-CF desde la factura (name puede ser TEMP-{id})
        invoice = self.account_move_id
        if not invoice:
            raise UserError(_('No hay factura vinculada a este registro XML.'))
        type_document = invoice.doc_type_E(invoice)

        # Debe coincidir con el XML: RFCE solo si plantilla RFCE (E32 < 250k DOP); si no, ECF.
        document_flow = 'ECF'
        if type_document == 'E32' and invoice._dgii_e32_is_rfce_simplified():
            document_flow = 'RFCE'
        elif type_document == 'B02':
            document_flow = 'RFCE'

        # Mismo contrato que factura / preview: un solo armador
        invoice_data = self.account_move_id._prepare_invoice_data_for_api(self.account_move_id)

        # API: mode=test → _submit_mock (XSD + tracking TEST-*); mode=prod → DGII real
        api_mode = 'test' if cre.dgii_client_mode == 'test' else 'prod'

        payload = cre._api_params_with_auth({
            'invoice_data': invoice_data,
            'type_document': type_document,
            'document_flow': document_flow,
            'mode': api_mode,
            'validate_xsd': cre.dgii_validate_xsd,
        })
        _logger.info(
            'DGII submit_invoice: api_mode=%s (itx.fe.dgii dgii_client_mode=%s)',
            api_mode,
            cre.dgii_client_mode,
        )

        try:
            response_data = cre._api_jsonrpc(
                'submit_invoice',
                payload,
                use_api_key=not cre._use_legacy_cert_in_request(),
                timeout=30,
            )

            # Store the full response
            self.json_response_sent = json.dumps(response_data)

            # Firma hecha en API antes de DGII: persistir siempre que vengan (éxito o fallo de recepción).
            if response_data.get('signed_xml'):
                self.signed_xml = response_data.get('signed_xml')
            if response_data.get('signature'):
                self.signature = response_data.get('signature')
            self._sync_signature_from_signed_xml_if_missing()

            # Process result based on new API response format
            if response_data.get('success'):
                self.status = 'sent'
                self.track_id = response_data.get('track_id')
                _logger.info("XML enviado exitosamente a DGII: %s, track_id: %s", self.name, self.track_id)

                self._enrich_api_response_with_dgii_json_from_error(response_data)
                self._apply_dgii_recepcion_from_submit(response_data)
            else:
                # Incluso con success=False el API suele devolver XML firmado (reintento / auditoría).
                # DGII a veces devuelve HTTP 400/422 con JSON en el texto ``error`` sin ``dgii_recepcion``.
                self._enrich_api_response_with_dgii_json_from_error(response_data)

                try:
                    self.json_response_sent = json.dumps(response_data)
                except (TypeError, ValueError):
                    pass

                # First apply the DGII reception data to populate dgi_err_msg from 'mensajes'
                self._apply_dgii_recepcion_from_submit(response_data)

                dgii_msgs = dgii_mensajes_text_from_response_data(response_data)
                if dgii_msgs:
                    self.dgi_err_msg = dgii_msgs

                # Use the DGII specific error message if available, otherwise construct from API message
                final_user_message = self.dgi_err_msg
                if not final_user_message:
                    # Detect XSD / validation errors (mock or API)
                    validation_errors = response_data.get('validation_errors') or response_data.get('errors')
                    # La API suele mandar "message" genérico y el detalle (auth, DGII body) en "error".
                    message = response_data.get('error') or response_data.get('message')

                    parts = []
                    if message:
                        parts.append(str(message))
                    if isinstance(validation_errors, list) and validation_errors:
                        parts.extend(str(e) for e in validation_errors if e)
                    elif validation_errors:
                        parts.append(str(validation_errors))
                    final_user_message = " | ".join(parts) if parts else None

                is_xsd_error = False
                if response_data.get('validation_errors'): # Check original validation_errors
                    is_xsd_error = True
                elif isinstance(final_user_message, str) and 'xsd' in final_user_message.lower():
                    is_xsd_error = True

                recoverable_rejection = self._is_recoverable_dgii_submission_rejection(
                    response_data, final_user_message
                )

                # Soft-handle XSD/validation failures: record in the itx.xml.data.dgii record
                if is_xsd_error:
                    self.status = 'error_no_enviado'
                    # Mirror DGII rejection semantics in UI
                    self.dgi_status = 'RECHAZADO'
                    self.dgi_err_msg = final_user_message or 'XSD validation failed' # Ensure it's not empty
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

                # Rechazo explícito DGII (mismo tratamiento que XSD): UI en itx.xml.data.dgii / factura
                if recoverable_rejection:
                    self.status = 'error_no_enviado'
                    if not self.dgi_status:
                        self.dgi_status = 'RECHAZADO'
                    # Always update dgi_err_msg with the more specific message if available
                    if final_user_message:
                        self.dgi_err_msg = final_user_message
                    elif dgii_msgs:
                        self.dgi_err_msg = dgii_msgs
                    elif not self.dgi_err_msg:
                        self.dgi_err_msg = _('Documento rechazado por DGII')

                    if response_data.get('track_id'):
                        self.track_id = response_data.get('track_id')
                    _logger.warning(
                        "DGII rechazó la recepción (itx_id=%s): %s",
                        self.id,
                        self.dgi_err_msg, # Use the already set or newly set dgi_err_msg
                    )
                    return response_data

                # Non-validation error: escalate as UserError (connection/auth/etc.)
                error_msg = final_user_message or (\
                    f"Error desconocido (status={response_data.get('status')})"\
                    if response_data.get('status') else 'Error desconocido'\
                )
                _logger.error('Error al enviar XML a DGII: %s', error_msg)
                self.dgi_err_msg = error_msg # Ensure this is also updated
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
            raw = self.json_response_sent
            if raw:
                try:
                    sent = json.loads(raw)
                except (ValueError, TypeError):
                    sent = {}
                if isinstance(sent, dict) and sent.get('success'):
                    self._apply_dgii_recepcion_from_submit(sent)
                    return
            raise UserError(_('No hay track_id disponible. Primero debe enviar el XML a DGII.'))

        cre = self.company_id.fe_dgii_id
        cre = cre.filtered(lambda p: p.active)
        if not cre:
            raise UserError(_('No hay ambiente activo configurado en esta compañia.'))

        if cre._use_legacy_cert_in_request():
            if not cre.certificate_file or not cre.certificate_password:
                raise UserError(
                    _('Configure certificado o sincronice con la API.')
                )
        else:
            cre._require_synced_for_prod()

        payload = cre._api_params_with_auth({'track_id': self.track_id})

        try:
            response_data = cre._api_jsonrpc(
                'check_status',
                payload,
                use_api_key=not cre._use_legacy_cert_in_request(),
                timeout=30,
            )

            # Store the full response
            self.json_response = json.dumps(response_data)

            # Check for API errors
            if not response_data.get('success'):
                error_msg = response_data.get('error', 'Error desconocido')
                _logger.error('API returned error: %s', error_msg)
                # Don't mark as error - might be still processing
                raise UserError(_('Error al verificar estado: %s') % error_msg)

            # Consulta DGII: prevalece dgii_status/estado real (no status técnico CHECKED/ACCEPTED).
            self._enrich_api_response_with_dgii_json_from_error(response_data)

            if response_data.get('signed_xml'):
                self.signed_xml = response_data.get('signed_xml')
            if response_data.get('signature'):
                self.signature = response_data.get('signature')
            self._sync_signature_from_signed_xml_if_missing()

            self._apply_dgii_recepcion_from_submit(response_data)

            dgii_label = self.dgi_status or dgii_estado_label_from_response(response_data)
            dgii_class = dgii_estado_classification(dgii_label)

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

            if not (self.qr_code or '').strip():
                self._assign_qr_code_after_recepcion(response_data)

            if dgii_class == 'approved':
                _logger.info(
                    "XML aprobado por DGII: %s, track_id: %s, estado=%s",
                    self.name, self.track_id, dgii_label,
                )
            elif dgii_class == 'conditional':
                _logger.warning(
                    "XML aceptado condicional DGII: %s, track_id: %s, estado=%s",
                    self.name, self.track_id, dgii_label,
                )
            elif dgii_class == 'rejected':
                _logger.error(
                    "XML rechazado por DGII: %s, track_id: %s, estado=%s, error: %s",
                    self.name, self.track_id, dgii_label, self.dgi_err_msg,
                )
            elif dgii_class == 'pending':
                _logger.info(
                    "XML pendiente en DGII: %s, track_id: %s, estado=%s",
                    self.name, self.track_id, dgii_label,
                )
            else:
                _logger.warning(
                    "Estado DGII no clasificado: status=%s dgii_status=%s label=%s track_id=%s",
                    response_data.get('status'),
                    response_data.get('dgii_status'),
                    dgii_label,
                    self.track_id,
                )

            if dgii_class in ('approved', 'conditional') and self.account_move_id and self.account_move_id.is_ecf_invoice and getattr(
                self.account_move_id.journal_id, 'is_dgii', False
            ):
                invoice_updates = {}
                if self.signature:
                    invoice_updates['l10n_do_ecf_security_code'] = self.signature
                sign_dt2 = self._ecf_sign_datetime_from_submit_response(response_data)
                if sign_dt2:
                    invoice_updates['l10n_do_ecf_sign_date'] = sign_dt2
                if invoice_updates:
                    self.account_move_id.write(invoice_updates)
                    _logger.info(
                        '[DGII][ecf_sign_date] verify invoice %s | campos=%s',
                        self.account_move_id.id,
                        list(invoice_updates.keys()),
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
        """
        Regenera el XML borrador con el mismo flujo que ``account.move.build_xml_to_print``
        (``_prepare_invoice_data_for_api`` + ``_call_dgii_api``). El código anterior
        armaba el payload con ``fe_dgii_id.read()`` / ``payment_ids.read()`` e incluía
        ``certificate_file`` en bytes → ``requests.post(..., json=)`` fallaba.
        """
        self.ensure_one()
        invoice = self.account_move_id
        if not invoice:
            raise UserError(_("No associated invoice record found."))
        type_document = invoice.doc_type_E(invoice)
        xml_content, xml_name = invoice.build_xml_to_print(invoice, type_document)
        if xml_content:
            self.xml_data = xml_content
            _logger.info(
                "XML reconstruido | itx_id=%s invoice=%s archivo=%s len=%s",
                self.id,
                invoice.id,
                xml_name,
                len(xml_content or ""),
            )

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
