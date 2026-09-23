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
