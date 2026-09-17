# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_ECF_ALLOWED_WITHOUT_MANUAL_NUMBER = {
    'minor', 'informal', 'exterior', False,
    'e-minor', 'e-informal', 'e-exterior', 'e-fiscal', 'e-consumer',
    'e-special', 'e-governmental', 'e-export', 'e-debit_note', 'e-credit_note',
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # WebPOS / BMC bridge (existing)
    # ------------------------------------------------------------------

    def _get_webpos_fiscal_document_number(self):
        """BMC: assign e-NCF via l10n_latam_sequence_id (accounting_update)."""
        self.ensure_one()
        if self.l10n_latam_sequence_id:
            return self.l10n_latam_sequence_id.next_by_id()
        return super()._get_webpos_fiscal_document_number()

    def _bmc_should_skip_webpos_send(self):
        """Skip WebPOS only for invoices imported via sync_objects_vbs."""
        self.ensure_one()
        return bool(getattr(self, 'sync_id', False) and self.sync_id)

    def _is_webpos_candidate_for_post(self):
        self.ensure_one()
        if not super()._is_webpos_candidate_for_post():
            return False
        return not self._bmc_should_skip_webpos_send()

    def _webpos_send_and_verify(self, raise_on_error=False):
        if self._bmc_should_skip_webpos_send():
            return False
        return super()._webpos_send_and_verify(raise_on_error=raise_on_error)

    def _is_manual_document_number(self):
        if self.journal_id.is_webpos and self._webpos_is_ecf_invoice():
            return False
        return super()._is_manual_document_number()

    def _check_l10n_latam_documents(self):
        validated_invoices = self.filtered(
            lambda x: x.l10n_latam_use_documents and x.state == 'posted'
        )
        without_doc_type = validated_invoices.filtered(
            lambda x: not x.l10n_latam_document_type_id
        )
        if without_doc_type:
            raise ValidationError(
                _(
                    "The journal require a document type but not document type "
                    "has been selected on invoices %s.",
                    without_doc_type.ids,
                )
            )

        for move in validated_invoices:
            without_number = (
                not move.l10n_latam_document_number
                and move.l10n_latam_manual_document_number
            )
            ncf_type = move.l10n_ncf_type_name

            if ncf_type in ('minor', 'e-minor') and without_number:
                if (
                    move.journal_id.l10n_latam_use_documents
                    and move.partner_id.vat != move.company_id.vat
                ):
                    raise ValidationError(
                        _(
                            'Minor expenses VAT must be the same as the company '
                            'reporting them.'
                        )
                    )

            if ncf_type not in _ECF_ALLOWED_WITHOUT_MANUAL_NUMBER and without_number:
                raise ValidationError(
                    _(
                        'Please set the document number on the following invoices %s.',
                        move.ids,
                    )
                )

        return super()._check_l10n_latam_documents()

    # ------------------------------------------------------------------
    # NC emitida WebPOS — helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bmc_ecf_prefix_from_ncf(ncf):
        ncf = (ncf or '').strip().upper()
        if ncf.startswith('E') and len(ncf) >= 3:
            return ncf[1:3]
        return ''

    @api.model
    def _bmc_is_webpos_ecf_prefix(self, prefix):
        if not prefix:
            return False
        return (
            prefix in self.E_CF_COMPRAS
            or prefix in self.E_CF_VENTAS
            or prefix in self.E_CF_AJUSTES
        )

    @api.model
    def _bmc_get_e_credit_note_document_type(self):
        doc_type = self.env.ref(
            'l10n_do_fix_report_invoice_bmc.ecf_credit_note_client',
            raise_if_not_found=False,
        )
        if doc_type:
            return doc_type
        return self.env['l10n_latam.document.type'].search(
            [
                ('country_id.code', '=', 'DO'),
                ('l10n_do_ncf_type', '=', 'e-credit_note'),
            ],
            limit=1,
        )

    def _bmc_webpos_fiscal_number(self):
        self.ensure_one()
        return (
            self.l10n_latam_document_number
            or self.l10n_do_fiscal_number
            or ''
        ).strip().upper()

    def _bmc_origin_ecf_prefix(self):
        self.ensure_one()
        origin = self.reversed_entry_id
        if origin:
            return self._bmc_ecf_prefix_from_ncf(origin._bmc_webpos_fiscal_number())
        return self._bmc_ecf_prefix_from_ncf(self.l10n_do_origin_ncf)

    def _bmc_is_issued_purchase_webpos_credit(self):
        self.ensure_one()
        return (
            self.move_type == 'in_refund'
            and self.journal_id.is_webpos
            and self.journal_id.type == 'purchase'
            and bool(self.reversed_entry_id)
        )

    def _bmc_is_issued_sale_webpos_credit(self):
        self.ensure_one()
        return (
            self.move_type == 'out_refund'
            and self.journal_id.is_webpos
            and self.journal_id.type == 'sale'
            and bool(self.reversed_entry_id)
        )

    def _bmc_is_issued_webpos_credit(self):
        self.ensure_one()
        return (
            self._bmc_is_issued_purchase_webpos_credit()
            or self._bmc_is_issued_sale_webpos_credit()
        )

    @staticmethod
    def _bmc_nc_days_since_origin(origin_move, nc_date):
        if not origin_move or not nc_date:
            return 0
        origin_date = origin_move.invoice_date or origin_move.date
        if not origin_date:
            return 0
        return (nc_date - origin_date).days

    def _bmc_is_nc_over_30_days(self, nc_date=None):
        self.ensure_one()
        if self.move_type not in ('out_refund', 'in_refund') or not self.reversed_entry_id:
            return False
        nc_date = nc_date or self.invoice_date or self.date
        return self._bmc_nc_days_since_origin(self.reversed_entry_id, nc_date) > 30

    @staticmethod
    def _bmc_tax_is_itbis(tax):
        group_name = (tax.tax_group_id.name or '').upper()
        if 'ITBIS' in group_name:
            return True
        tax_name = (tax.name or '').upper()
        return 'ITBIS' in tax_name and 'ISR' not in tax_name

    def _bmc_get_exempt_itbis_tax(self):
        self.ensure_one()
        company = self.company_id
        if self.move_type in ('out_refund', 'out_invoice'):
            tax_use = 'sale'
            xmlid = f'l10n_do.{company.id}_tax_0_sale'
        else:
            tax_use = 'purchase'
            xmlid = f'l10n_do.{company.id}_tax_0_purch'
        tax = self.env.ref(xmlid, raise_if_not_found=False)
        if tax and tax.company_id == company:
            return tax
        return self.env['account.tax'].search([
            ('company_id', '=', company.id),
            ('type_tax_use', '=', tax_use),
            ('amount', '=', 0.0),
            '|',
            ('tax_group_id.name', 'ilike', 'ITBIS'),
            ('name', 'ilike', 'EXENTO'),
        ], limit=1)

    def _bmc_apply_nc_over_30_exempt_taxes(self, nc_date=None):
        """DGII: NC >30 días desde factura origen → líneas sin ITBIS, solo EXENTO."""
        self.ensure_one()
        if not self._bmc_is_nc_over_30_days(nc_date=nc_date):
            return False
        exempt_tax = self._bmc_get_exempt_itbis_tax()
        if not exempt_tax:
            return False

        product_lines = self.invoice_line_ids.filtered(
            lambda line: line.display_type in (False, 'product')
        )
        for line in product_lines:
            keep_taxes = line.tax_ids.filtered(
                lambda tax: not self._bmc_tax_is_itbis(tax)
            )
            new_taxes = keep_taxes | exempt_tax
            line.tax_ids = [(6, 0, new_taxes.ids)]
        return True

    def _bmc_webpos_applies_e41_injection(self):
        self.ensure_one()
        if self.move_type not in ('in_invoice', 'in_refund'):
            return False
        if self.move_type == 'in_refund' and self._bmc_is_nc_over_30_days():
            return False
        if self._bmc_ecf_prefix_from_ncf(self._bmc_webpos_fiscal_number()) == 'E41':
            return True
        return (
            self.move_type == 'in_refund'
            and self._bmc_origin_ecf_prefix() == 'E41'
        )

    def _bmc_webpos_applies_e47_injection(self):
        self.ensure_one()
        if self.move_type not in ('in_invoice', 'in_refund'):
            return False
        if self._bmc_ecf_prefix_from_ncf(self._bmc_webpos_fiscal_number()) == 'E47':
            return True
        return (
            self.move_type == 'in_refund'
            and self._bmc_origin_ecf_prefix() == 'E47'
        )

    def _bmc_webpos_is_e41_purchase(self):
        """Backward-compatible alias."""
        return self._bmc_webpos_applies_e41_injection()

    # ------------------------------------------------------------------
    # NC emitida — create / reverse defaults
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            journal_id = vals.get('journal_id')
            move_type = vals.get('move_type')
            if not journal_id or move_type not in ('in_refund', 'out_refund'):
                continue
            journal = self.env['account.journal'].browse(journal_id)
            if not journal.l10n_latam_use_documents or not journal.is_webpos:
                continue
            doc_type = self._bmc_get_e_credit_note_document_type()
            if doc_type:
                vals['l10n_latam_document_type_id'] = doc_type.id
        return super().create(vals_list)

    def _reverse_move_vals(self, default_values, cancel=True):
        res = super()._reverse_move_vals(default_values, cancel=cancel)
        self.ensure_one()
        if self.l10n_latam_country_code != 'DO':
            return res
        journal = self.journal_id
        if not journal.l10n_latam_use_documents or not journal.is_webpos:
            return res

        origin_prefix = self._bmc_ecf_prefix_from_ncf(self._bmc_webpos_fiscal_number())
        if not self._bmc_is_webpos_ecf_prefix(origin_prefix):
            return res

        doc_type = self._bmc_get_e_credit_note_document_type()
        if doc_type:
            res['l10n_latam_document_type_id'] = doc_type.id

        origin_ncf = self.l10n_latam_document_number or self.l10n_do_fiscal_number
        if origin_ncf:
            res['l10n_do_origin_ncf'] = origin_ncf

        if self.is_ecf_invoice and 'l10n_do_ecf_modification_code' not in res:
            mod_code = self.env.context.get('l10n_do_ecf_modification_code')
            if mod_code:
                res['l10n_do_ecf_modification_code'] = mod_code

        return res

    # ------------------------------------------------------------------
    # WebPOS overrides — doc type / modification code
    # ------------------------------------------------------------------

    def doc_type_E(self, invoice):
        if invoice._bmc_is_issued_webpos_credit():
            return 'C'
        return super().doc_type_E(invoice)

    def _get_webpos_ecf_modification_code(self, invoice):
        if (
            invoice.move_type in ('out_refund', 'in_refund')
            and invoice.reversed_entry_id
            and invoice.journal_id.is_webpos
        ):
            original_invoice = invoice.reversed_entry_id
            current_amount = abs(invoice.amount_total or 0.0)
            original_amount = abs(original_invoice.amount_total or 0.0)
            if abs(current_amount - original_amount) < 0.01:
                return '1'
            return '3'
        return super()._get_webpos_ecf_modification_code(invoice)

    # ------------------------------------------------------------------
    # E41 compras BMC: retención ITBIS solo en XML (factura sin imp. neg.)
    # ------------------------------------------------------------------

    @staticmethod
    def _bmc_webpos_payload_line_has_withholding(line_taxes):
        for tax in line_taxes or []:
            if (tax.get('amount') or 0.0) < 0.0:
                return True
        return False

    def _bmc_webpos_payload_line_has_isr_withholding(self, line_taxes):
        for tax in line_taxes or []:
            if (tax.get('amount') or 0.0) >= 0.0:
                continue
            group_id = tax.get('tax_group_id')
            if group_id:
                group_name = (
                    self.env['account.tax.group'].browse(group_id).name or ''
                ).upper()
                if 'ISR' in group_name or 'RETENCION' in group_name:
                    return True
            elif 'ISR' in (tax.get('name') or '').upper():
                return True
        return False

    def _bmc_webpos_find_itbis_retention_tax(self, itbis_rate):
        """100% ITBIS retenido: impuesto purchase con tasa -itbis_rate."""
        self.ensure_one()
        Tax = self.env['account.tax']
        target_amount = -abs(itbis_rate)
        param_tax_id = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_do_fix_report_invoice_bmc.e41_itbis_retention_tax_id'
        )
        if param_tax_id and str(param_tax_id).isdigit():
            tax = Tax.browse(int(param_tax_id)).exists()
            if (
                tax
                and tax.company_id == self.company_id
                and tax.type_tax_use == 'purchase'
                and tax.amount == target_amount
            ):
                return tax
        domain = [
            ('company_id', '=', self.company_id.id),
            ('type_tax_use', '=', 'purchase'),
            ('amount', '=', target_amount),
            ('tax_group_id.name', 'ilike', 'ITBIS'),
        ]
        tax = Tax.search(domain + [('name', 'ilike', '100%')], limit=1)
        return tax or Tax.search(domain, limit=1)

    def _bmc_webpos_find_isr_retention_tax(self):
        """ISR retenido en compras/E47 cuando solo existe income_withholding."""
        self.ensure_one()
        Tax = self.env['account.tax']
        param_tax_id = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_do_fix_report_invoice_bmc.e47_isr_retention_tax_id'
        )
        if param_tax_id and str(param_tax_id).isdigit():
            tax = Tax.browse(int(param_tax_id)).exists()
            if (
                tax
                and tax.company_id == self.company_id
                and tax.type_tax_use == 'purchase'
                and (tax.amount or 0.0) < 0.0
            ):
                return tax

        for line in self.line_ids.filtered(lambda l: l.tax_line_id):
            tax = line.tax_line_id
            if (tax.amount or 0.0) >= 0.0 or tax.type_tax_use != 'purchase':
                continue
            group_name = (tax.tax_group_id.name or '').upper()
            if 'ISR' in group_name or 'RETENCION' in group_name:
                return tax

        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                if (tax.amount or 0.0) >= 0.0:
                    continue
                group_name = (tax.tax_group_id.name or '').upper()
                if 'ISR' in group_name or 'RETENCION' in group_name:
                    return tax

        return Tax.search(
            [
                ('company_id', '=', self.company_id.id),
                ('type_tax_use', '=', 'purchase'),
                ('amount', '<', 0),
                '|',
                ('tax_group_id.name', 'ilike', 'ISR'),
                ('tax_group_id.name', 'ilike', 'RETENCION'),
            ],
            limit=1,
        )

    @staticmethod
    def _bmc_webpos_tax_payload_from_record(tax):
        return {
            'name': tax.name or '',
            'amount': tax.amount or 0.0,
            'price_include': tax.price_include or False,
            'tax_group_id': tax.tax_group_id.id if tax.tax_group_id else False,
        }

    def _bmc_webpos_inject_e41_withholding_taxes(self, lines_data):
        """Inyecta retención ITBIS al payload WebPOS si la factura no la trae."""
        self.ensure_one()
        if not self._bmc_webpos_applies_e41_injection():
            return lines_data
        for line_data in lines_data:
            taxes = list(line_data.get('tax_ids') or [])
            if self._bmc_webpos_payload_line_has_withholding(taxes):
                continue
            positive_itbis = [
                t for t in taxes
                if (t.get('amount') or 0.0) > 0.0
                and (
                    t.get('tipo_impuesto_webpos_itbis')
                    or 'ITBIS' in (t.get('name') or '').upper()
                )
            ]
            if not positive_itbis:
                continue
            for itbis_tax in positive_itbis:
                wh_tax = self._bmc_webpos_find_itbis_retention_tax(itbis_tax['amount'])
                if not wh_tax:
                    continue
                wh_payload = self._bmc_webpos_tax_payload_from_record(wh_tax)
                if any(
                    (t.get('amount') or 0.0) == wh_payload['amount']
                    and (t.get('name') or '') == wh_payload['name']
                    for t in taxes
                ):
                    continue
                taxes.append(wh_payload)
            line_data['tax_ids'] = taxes
            # BMC registra ITBIS bruto; el XML E41 lleva retención aparte (neto = base).
            line_data['price_total'] = (
                line_data.get('price_subtotal') or line_data.get('price_total')
            )
        return lines_data

    def _bmc_webpos_inject_e47_isr_taxes(self, lines_data):
        """Inyecta retención ISR al payload WebPOS (E47 / income_withholding)."""
        self.ensure_one()
        if not self._bmc_webpos_applies_e47_injection():
            return lines_data
        if not (self.income_withholding or 0.0) > 0.0:
            return lines_data

        wh_tax = self._bmc_webpos_find_isr_retention_tax()
        if not wh_tax:
            return lines_data

        wh_payload = self._bmc_webpos_tax_payload_from_record(wh_tax)
        for line_data in lines_data:
            taxes = list(line_data.get('tax_ids') or [])
            if self._bmc_webpos_payload_line_has_isr_withholding(taxes):
                continue
            if any(
                (t.get('amount') or 0.0) == wh_payload['amount']
                and (t.get('name') or '') == wh_payload['name']
                for t in taxes
            ):
                continue
            taxes.append(wh_payload)
            line_data['tax_ids'] = taxes
        return lines_data

    def _prepare_invoice_data_for_api(self, invoice):
        data = super()._prepare_invoice_data_for_api(invoice)
        if invoice.journal_id.is_webpos and invoice._webpos_is_ecf_invoice():
            lines = data.get('lines') or []
            lines = invoice._bmc_webpos_inject_e41_withholding_taxes(lines)
            lines = invoice._bmc_webpos_inject_e47_isr_taxes(lines)
            data['lines'] = lines
            if data.get('record'):
                data['record']['lines'] = lines
        return data


    bmc_ecf_qr_data_uri = fields.Char(compute='_compute_bmc_ecf_qr_data_uri')

    def _compute_bmc_ecf_qr_data_uri(self):
        for rec in self:
            rec.bmc_ecf_qr_data_uri = rec._bmc_get_ecf_qr_data_uri()

    def _bmc_get_ecf_qr_raw_url(self):
        """URL cruda del timbre DGII para el QR (WebPOS o sello estandar)."""
        self.ensure_one()
        raw = getattr(self, 'l10n_do_webpos_electronic_stamp', False) or self.l10n_do_electronic_stamp
        if not raw:
            return False
        from urllib.parse import unquote
        if '%' in raw:
            raw = unquote(raw)
        return raw

    def _bmc_get_ecf_qr_data_uri(self):
        """PNG del QR embebido. Evita que wkhtmltopdf pierda /report/barcode/."""
        self.ensure_one()
        raw = self._bmc_get_ecf_qr_raw_url()
        if not raw:
            return False
        import base64
        try:
            img = self.env['ir.actions.report'].barcode('QR', raw, width=140, height=140)
        except Exception:
            return False
        return 'data:image/png;base64,%s' % base64.b64encode(img).decode()


class MyXmlData(models.Model):
    _inherit = 'my.xml.data'

    def _bmc_sync_report_electronic_stamp(self):
        """Bridge: accounting_update PDF reads l10n_do_electronic_stamp, not WebPOS field."""
        move = self.account_move_id
        if not move or not self.qr_code:
            return
        if 'l10n_do_electronic_stamp' in move._fields:
            move.l10n_do_electronic_stamp = self._webpos_sanitize_api_text(self.qr_code)

    def verify_sent_encf(self, raise_on_error=True):
        res = super().verify_sent_encf(raise_on_error=raise_on_error)
        if res:
            self._bmc_sync_report_electronic_stamp()
        return res
