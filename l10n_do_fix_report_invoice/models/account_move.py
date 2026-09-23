# -*- coding: utf-8 -*-

from odoo import models

WEBPOS_ECF_INVOICE_REPORT = 'l10n_do_fix_report_invoice.report_invoice_document_webpos_ecf'


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_name_invoice_report(self):
        self.ensure_one()
        if self.journal_id.is_webpos and self.is_ecf_invoice:
            return WEBPOS_ECF_INVOICE_REPORT
        return super()._get_name_invoice_report()

    def _webpos_ecf_report_fiscal_number(self):
        self.ensure_one()
        return (self.l10n_latam_document_number or '').strip()

    def _webpos_ecf_report_document_title(self):
        self.ensure_one()
        doc_type = self.l10n_latam_document_type_id
        if doc_type and doc_type.report_name:
            return doc_type.report_name
        return 'Factura electrónica'

    def _webpos_ecf_report_ncf_valid_until(self):
        """Optional field from other modules; never required at install."""
        self.ensure_one()
        exp = getattr(self, 'l10n_do_ncf_expiration_date', False)
        return exp.strftime('%d/%m/%Y') if exp else ''

    def _webpos_ecf_report_origin_ncf(self):
        self.ensure_one()
        return getattr(self, 'l10n_do_origin_ncf', False) or ''
