# -*- coding: utf-8 -*-

from odoo import api, models, _
from odoo.exceptions import RedirectWarning, ValidationError


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def _get_l10n_do_fiscal_sequence_mode(self):
        self.ensure_one()
        if not self.company_id.l10n_do_ecf_issuer:
            return "b"
        return self.company_id.l10n_do_fiscal_sequence_mode or "b"

    @api.model
    def _get_l10n_do_ncf_types_data(self):
        """Return the full NCF types dictionary including electronic (e-*) types.

        Extends the base l10n_do_accounting dictionary to include all ECF types
        needed for Dominican Republic electronic invoicing (e-fiscal, e-consumer,
        e-informal, e-minor, e-special, e-governmental, e-export, e-exterior).

        :return: dict with "issued" and "received" keys, each containing
                 sub-dicts keyed by DGII tax payer type with lists of NCF type codes
        """
        return {
            "issued": {
                "taxpayer": ["fiscal", "e-fiscal"],
                "non_payer": ["consumer", "unique", "e-consumer"],
                "nonprofit": ["fiscal", "e-fiscal"],
                "special": ["special", "e-special"],
                "governmental": ["governmental", "e-governmental"],
                "foreigner": ["export", "consumer", "e-export", "e-consumer"],
            },
            "received": {
                "taxpayer": ["fiscal", "special", "governmental", "e-fiscal", "e-governmental", "e-special"],
                "non_payer": ["informal", "minor", "e-informal", "e-minor"],
                "nonprofit": ["special", "fiscal", "e-special", "e-fiscal"],
                "special": ["special", "e-special"],
                "governmental": ["governmental", "e-governmental"],
                "foreigner": ["exterior", "e-exterior", "import"],
            },
        }

    def _get_journal_ncf_types(self, counterpart_partner=False, invoice=False):
        """Get allowed NCF/ECF types for this journal, respecting fiscal sequence mode.

        Regarding the DGII type of company and the type of journal
        (sale/purchase), get the allowed NCF types. Optionally, receive
        the counterpart partner (customer/supplier) and get the allowed
        NCF types to work with him. This method is used to populate
        document types on journals and also to filter document types on
        specific invoices to/from customer/supplier.

        Integrates _get_l10n_do_fiscal_sequence_mode() to respect the
        configured mode (b, e, or both) when returning types.

        :param counterpart_partner: res.partner record to filter types for
        :param invoice: account.move record for context-specific filtering
        :return: list of NCF type strings filtered by mode
        """
        self.ensure_one()
        ncf_types_data = self._get_l10n_do_ncf_types_data()

        if not self.company_id.vat:
            action = self.env.ref("base.action_res_company_form")
            msg = _("Cannot create chart of account until you configure your VAT.")
            raise RedirectWarning(msg, action.id, _("Go to Companies"))

        # Get all the ncf_types values from the nested dictionary, remove duplicates and
        # convert it into a list
        ncf_types = list(
            set(
                [
                    value
                    for dic in ncf_types_data[
                        "issued" if self.type == "sale" else "received"
                    ].values()
                    for value in dic
                ]
            )
        )

        if not counterpart_partner:
            ncf_notes = ["debit_note", "credit_note"]
            ncf_external = ["fiscal", "special", "governmental", "e-fiscal", "e-special", "e-governmental"]

            # When Journal fiscal sequence create, include ncf_notes if sale
            # or exclude ncf_external if purchase
            res = (
                ncf_types + ncf_notes
                if self.type == "sale"
                else [ncf for ncf in ncf_types if ncf not in ncf_external]
            )
            return self._get_all_ncf_types(res)

        if counterpart_partner.l10n_do_dgii_tax_payer_type:
            counterpart_ncf_types = ncf_types_data[
                "issued" if self.type == "sale" else "received"
            ][counterpart_partner.l10n_do_dgii_tax_payer_type]
            ncf_types = list(set(ncf_types) & set(counterpart_ncf_types))
        else:
            raise ValidationError(
                _("Partner %s is needed to issue a fiscal invoice")
                % self._fields["l10n_do_dgii_tax_payer_type"].string
            )

        if invoice and invoice.move_type in ["out_refund", "in_refund"]:
            ncf_types = ["credit_note"]

        return self._get_all_ncf_types(ncf_types, invoice)

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

    def _get_l10n_do_document_types_domain(self, exclude_existing=False):
        """Build search domain for l10n_latam.document.type records.

        Uses _get_journal_ncf_types() and _get_journal_codes() which are
        overridden in this module to respect the fiscal sequence mode
        (b, e, or both), ensuring electronic document types (E41, etc.)
        are properly included when needed.

        :param exclude_existing: if True, exclude document types already
                                 having sequences in this journal
        :return: list of domain tuples for l10n_latam.document.type search
        """
        self.ensure_one()
        domain = [
            ("country_id.code", "=", "DO"),
            ("internal_type", "in", ["invoice", "in_invoice", "debit_note", "credit_note"]),
            ("active", "=", True),
            "|",
            ("l10n_do_ncf_type", "=", False),
            ("l10n_do_ncf_type", "in", self._get_journal_ncf_types()),
        ]
        codes = self._get_journal_codes()
        if codes:
            domain.append(("code", "in", codes))
        if exclude_existing:
            existing_ids = [dt.id for dt in self.l10n_do_sequence_ids.l10n_latam_document_type_id if dt]
            if existing_ids:
                domain.insert(0, ("id", "not in", existing_ids))
        return domain

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
        domain = self._get_l10n_do_document_types_domain(exclude_existing=True)
        documents = self.env["l10n_latam.document.type"].search(domain)
        for document in documents:
            vals = document._get_document_sequence_vals_2(self)
            sequences |= self.env["ir.sequence"].create(vals)
        return sequences

    @api.model
    def generate_missing_fiscal_sequences_for_company(self, company):
        if isinstance(company, (int, list)):
            company = self.env["res.company"].browse(company)
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

    @api.model
    def diagnostic_get_journal_ncf_types(self, journal_id, partner_id=False):
        """Public diagnostic method - returns NCF types for a given journal/partner.

        Called remotely via XMLRPC for debugging the document type selection
        on purchase invoices with informal (non_payer) suppliers.

        :param journal_id: int, ID of account.journal
        :param partner_id: int or False, ID of res.partner
        :return: dict with debug info
        """
        journal = self.browse(journal_id)
        if not journal.exists():
            return {"error": "Journal not found"}
        partner = self.env["res.partner"].browse(partner_id) if partner_id else False
        ncf_types = journal._get_journal_ncf_types(counterpart_partner=partner) if partner else journal._get_journal_ncf_types()
        codes = journal._get_journal_codes()
        mode = journal._get_l10n_do_fiscal_sequence_mode()
        ecf_issuer = journal.company_id.l10n_do_ecf_issuer
        company_mode = journal.company_id.l10n_do_fiscal_sequence_mode
        # Build the domain that would be used in _get_l10n_latam_documents_domain
        domain = [
            ("country_id.code", "=", "DO"),
            ("internal_type", "in", ["invoice", "in_invoice", "debit_note", "credit_note"]),
            ("active", "=", True),
            "|",
            ("l10n_do_ncf_type", "=", False),
            ("l10n_do_ncf_type", "in", ncf_types),
        ]
        if codes:
            domain.append(("code", "in", codes))
        docs = self.env["l10n_latam.document.type"].search(domain)
        return {
            "journal_id": journal.id,
            "journal_name": journal.name,
            "journal_type": journal.type,
            "company_id": journal.company_id.id,
            "company_name": journal.company_id.name,
            "ecf_issuer": ecf_issuer,
            "company_mode": company_mode,
            "effective_mode": mode,
            "ncf_types": ncf_types,
            "codes": codes,
            "available_documents": [
                {"id": d.id, "name": d.name, "code": d.code, "prefix": d.doc_code_prefix, "ncf_type": d.l10n_do_ncf_type}
                for d in docs
            ],
            "existing_sequences": [
                {"id": s.id, "prefix": s.prefix, "document_type_id": s.l10n_latam_document_type_id.id if s.l10n_latam_document_type_id else None}
                for s in journal.l10n_do_sequence_ids
            ],
        }

    @api.model
    def force_regenerate_fiscal_sequences(self, journal_id=False):
        """Force regeneration of fiscal sequences for a specific journal or all journals.
        
        Called remotely via XMLRPC. Creates missing sequences for the specified
        journal (or all DO fiscal journals if no journal_id given).
        
        :param journal_id: int, ID of account.journal (optional)
        :return: dict with results
        """
        if journal_id:
            journals = self.browse(journal_id)
            if not journals.exists():
                return {"error": f"Journal {journal_id} not found"}
        else:
            journals = self.search([
                ("l10n_latam_use_documents", "=", True),
                ("type", "in", ("sale", "purchase")),
            ]).filtered(lambda j: j.company_id.country_id == self.env.ref("base.do"))
        
        created = []
        for journal in journals:
            before_ids = set(journal.l10n_do_sequence_ids.ids)
            journal._generate_missing_fiscal_sequences()
            after_ids = set(journal.l10n_do_sequence_ids.ids)
            new_ids = after_ids - before_ids
            created.append({
                "journal_id": journal.id,
                "journal_name": journal.name,
                "before_count": len(before_ids),
                "after_count": len(after_ids),
                "created_ids": list(new_ids),
            })
        
        return {
            "journals_processed": len(journals),
            "results": created,
        }