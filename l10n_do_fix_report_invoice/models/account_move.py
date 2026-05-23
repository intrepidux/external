# -*- coding: utf-8 -*-

from odoo import models, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"

    def _l10n_do_set_next_sequence(self):
        self.ensure_one()

        # Si partner es la propia empresa, establecer tipo de documento
        partner_companies = self.env['res.company'].sudo().search([]).mapped('partner_id')
        is_company = self.partner_id.id in partner_companies.ids
        if is_company and self.partner_id.id == self.company_id.partner_id.id and self.move_type == 'out_invoice':
            l10n_latam_document_type_id = self.env.ref('l10n_do_accounting_yasmany.ncf_consumer_supplier')
            if self.company_id.l10n_do_ecf_issuer:
                l10n_latam_document_type_id = self.env.ref('l10n_do_accounting_yasmany.ecf_consumer_supplier')
            self.write({
                'l10n_latam_document_type_id': l10n_latam_document_type_id.id
            })

        # Lógica condicional solo para E33 y E34
        use_shared_sequence = (
            self.l10n_latam_document_type_id
            and self.l10n_latam_document_type_id.l10n_do_ncf_type in ("e-credit_note", "e-debit_note")
        )

        target_journal = self.journal_id
        if use_shared_sequence:
            # Buscar diario fuente compartido (siempre de tipo 'sale')
            shared_source = self.env['account.journal'].search([
                ('l10n_do_is_shared_sequence_source', '=', True),
                ('company_id', '=', self.company_id.id),
                ('type', '=', 'sale') # <-- Forzar tipo 'sale'
            ], limit=1)
            if shared_source:
                target_journal = shared_source

        journal_document_type = self.env[
            'l10n_do.account.journal.document_type'].search([
                ('journal_id', '=', target_journal.id),
                ('l10n_latam_document_type_id', '=',
                 self.l10n_latam_document_type_id.id)
            ], limit=1)
        if not journal_document_type:
            doc_type = self.l10n_latam_document_type_id.name if self.l10n_latam_document_type_id else "No definido"
            _logger.info(f"Datos: Diario - {target_journal.name} | Tipo de Documento: {doc_type}")
            raise UserError("Tipo de documento de diario no encontrado.")

        doc_type = self.l10n_latam_document_type_id
        doc_types = ['B01', 'B03', 'B04', 'E31']
        if (
                self.move_type in ['in_invoice', 'in_refund'] and
                doc_type.doc_code_prefix in doc_types and
                self.ref
        ):
            self.write({
                'l10n_do_fiscal_number': self.ref,
                'l10n_do_ncf_expiration_date': journal_document_type.l10n_do_ncf_expiration_date,
            })
            return True

        self.write({
            'l10n_do_fiscal_number': journal_document_type._set_next_sequence(),
            'l10n_do_ncf_expiration_date': journal_document_type.l10n_do_ncf_expiration_date,
        })
        return True

    def _is_l10n_do_manual_document_number(self):
        result = super()._is_l10n_do_manual_document_number()

        # Tu parche: notas electrónicas (E33/E34) NO son manuales
        if self.l10n_latam_document_type_id and self.l10n_latam_document_type_id.l10n_do_ncf_type in ("e-credit_note", "e-debit_note"):
            return False

        if self.reversed_entry_id and \
            self.reversed_entry_id.l10n_latam_document_type_id.l10n_do_ncf_type in ("e-informal", "e-minor", "e-exterior"):
            return False

        return result