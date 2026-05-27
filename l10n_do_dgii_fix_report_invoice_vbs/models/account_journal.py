# -*- coding: utf-8 -*-

from odoo import api, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def _get_l10n_do_fiscal_sequence_mode(self):
        self.ensure_one()
        if not self.company_id.l10n_do_ecf_issuer:
            return "b"
        return self.company_id.l10n_do_fiscal_sequence_mode or "b"

    def _get_all_ncf_types(self, types_list, invoice=False):
        self.ensure_one()
        base_types = []
        ecf_types = []
        for doc_type in types_list:
            if not doc_type:
                continue
            if doc_type.startswith("e-"):
                if doc_type not in ecf_types:
                    ecf_types.append(doc_type)
                continue
            if doc_type not in base_types:
                base_types.append(doc_type)
            if doc_type not in ("unique", "import"):
                ecf_type = "e-%s" % doc_type
                if ecf_type not in ecf_types:
                    ecf_types.append(ecf_type)

        mode = self._get_l10n_do_fiscal_sequence_mode()
        if mode == "e":
            return ecf_types
        if mode == "both":
            return base_types + ecf_types
        return base_types

    def _get_journal_codes(self):
        self.ensure_one()
        if self.type not in ("sale", "purchase"):
            return []
        mode = self._get_l10n_do_fiscal_sequence_mode()
        if mode == "e":
            return ["E"]
        if mode == "both":
            return ["B", "E"]
        return ["B"]

    def _generate_missing_fiscal_sequences(self):
        if not self:
            return self.env["ir.sequence"]
        if len(self) > 1:
            sequences = self.env["ir.sequence"]
            for journal in self:
                sequences |= journal._generate_missing_fiscal_sequences()
            return sequences

        self.ensure_one()
        if self.company_id.country_id != self.env.ref("base.do") or not self.l10n_latam_use_documents:
            return self.env["ir.sequence"]

        sequences = self.env["ir.sequence"]
        documents = self.env["l10n_latam.document.type"].search(
            self._get_l10n_do_document_types_domain(exclude_existing=True)
        )
        for document in documents:
            sequences |= self.env["ir.sequence"].create(
                document._get_document_sequence_vals_2(self)
            )
        return sequences

    @api.model
    def generate_missing_fiscal_sequences_for_company(self, company):
        if not company or company.country_id != self.env.ref("base.do"):
            return self.env["ir.sequence"]
        journals = self.search([
            ("company_id", "=", company.id),
            ("l10n_latam_use_documents", "=", True),
            ("type", "in", ("sale", "purchase")),
        ])
        return journals._generate_missing_fiscal_sequences()

    @api.model
    def generate_missing_fiscal_sequences(self):
        journals = self.search([
            ("l10n_latam_use_documents", "=", True),
            ("type", "in", ("sale", "purchase")),
        ]).filtered(lambda journal: journal.company_id.country_id == self.env.ref("base.do"))
        return journals._generate_missing_fiscal_sequences()
