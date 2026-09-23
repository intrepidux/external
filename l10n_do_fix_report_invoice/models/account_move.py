# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError

WEBPOS_ECF_INVOICE_REPORT = 'l10n_do_fix_report_invoice.report_invoice_document_webpos_ecf'


class AccountMove(models.Model):
    _inherit = 'account.move'

    webpos_api_pdf_ready = fields.Boolean(
        string='PDF WebPOS disponible',
        compute='_compute_webpos_api_pdf_ready',
    )

    @api.depends(
        'xml_data_id.pdf',
        'xml_data_id.status',
    )
    def _compute_webpos_api_pdf_ready(self):
        for move in self:
            xml_rec = move.xml_data_id
            move.webpos_api_pdf_ready = bool(
                xml_rec
                and xml_rec.pdf
                and xml_rec.status == 'procesed'
            )

    def _get_name_invoice_report(self):
        self.ensure_one()
        if self.journal_id.is_webpos and self.is_ecf_invoice:
            return WEBPOS_ECF_INVOICE_REPORT
        return super()._get_name_invoice_report()

    def _webpos_ecf_report_fiscal_number(self):
        self.ensure_one()
        return (self.l10n_latam_document_number or '').strip()

    def _webpos_ecf_report_company_vat(self):
        """RNC emisor; fallback matriz (sucursal) sin depender de l10n_do_accounting."""
        self.ensure_one()
        company = self.company_id
        return (company.vat or company.sudo().root_id.vat or '').strip()

    def _webpos_ecf_report_document_title(self):
        self.ensure_one()
        doc_type = self.l10n_latam_document_type_id
        if doc_type and doc_type.report_name:
            return doc_type.report_name
        return 'Factura electrónica'

    def _webpos_ecf_report_show_ncf_valid_until(self):
        """Misma lógica que fiscal_exp_date en forks DO (campos opcionales)."""
        self.ensure_one()
        if not self._webpos_ecf_report_fiscal_number():
            return False
        if not getattr(self, 'l10n_latam_use_documents', False):
            return False
        if self.move_type not in ('out_invoice', 'out_refund'):
            return False
        if self.state != 'posted':
            return False
        doc_type = self.l10n_latam_document_type_id
        if not doc_type or not doc_type.doc_code_prefix:
            return False
        prefix_tail = doc_type.doc_code_prefix[1:]
        if prefix_tail in ('32', '34'):
            return False
        return bool(getattr(self, 'l10n_do_ncf_expiration_date', False))

    def _webpos_ecf_report_ncf_valid_until(self):
        self.ensure_one()
        exp = getattr(self, 'l10n_do_ncf_expiration_date', False)
        return exp.strftime('%d/%m/%Y') if exp else ''

    def _webpos_ecf_report_origin_ncf(self):
        self.ensure_one()
        return getattr(self, 'l10n_do_origin_ncf', False) or ''

    def action_print_webpos_api_pdf(self):
        """Abre el PDF devuelto por WebPOS (verify_status), no el reporte QWeb de Odoo."""
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_('La factura debe estar publicada.'))
        if not self.journal_id.is_webpos or not self.is_ecf_invoice:
            raise UserError(_('Solo aplica a comprobantes e-CF en diario WebPOS.'))
        if not self.webpos_api_pdf_ready:
            raise UserError(
                _('El PDF WebPOS solo está disponible tras verificar DGII y recibir el archivo desde la API.')
            )
        xml_rec = self.xml_data_id
        filename = (self.l10n_latam_document_number or self.name or 'webpos').replace('/', '-')
        return {
            'type': 'ir.actions.act_url',
            'url': (
                f'/web/content/my.xml.data/{xml_rec.id}/pdf/'
                f'{filename}.pdf?download=true'
            ),
            'target': 'new',
        }
