#  Copyright (c) 2020 - Indexa SRL. (https://www.indexa.do) <info@indexa.do>
#  See LICENSE file for full licensing details.

import ast
import json
import base64
import logging
import requests
from datetime import datetime as dt
from collections import OrderedDict as od
from datetime import datetime
from datetime import datetime, timedelta
from dateutil.parser import parse
import time
from lxml import etree as ET

import hashlib
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, RedirectWarning, UserError
from werkzeug import urls
import random
import pytz
import odoo.addons.decimal_precision as dp

from dicttoxml import dicttoxml



_logger = logging.getLogger(__name__)

ECF_STATE_MAP = {
    "Aceptado": "delivered_accepted",
    "AceptadoCondicional": "conditionally_accepted",
    "EnProceso": "delivered_pending",
    "Rechazado": "delivered_refused",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.constrains("name", "partner_id", "company_id")
    def _check_unique_vendor_number(self):

        l10n_do_invoice = self.filtered(
            lambda inv: inv.l10n_latam_country_code == "DO"
                        and inv.l10n_latam_use_documents
                        and inv.is_purchase_document()
                        and inv.l10n_latam_document_number and inv.state == 'posted'
        )

        if self.env.context.get("skip_vendor_number_validation"):
            return

        for rec in l10n_do_invoice:
            domain = [
                ("move_type", "=", rec.move_type),
                ("ref", "=", rec.ref),
                ("company_id", "=", rec.company_id.id),
                ("id", "!=", rec.id),('state','=','posted'),
                ('state', '=', 'posted'),('journal_id.l10n_latam_use_documents', '=', True),
                ("partner_id", "=", rec.partner_id.id),
            ]
            if rec.search(domain):
                raise ValidationError(
                    _("El NCF de la factura de proveedor debe ser único por proveedor y empresa.")
                )
        return super(AccountMove, self - l10n_do_invoice)._check_unique_vendor_number()

    @api.constrains("move_type", "l10n_latam_document_type_id")
    def _check_invoice_type_document_type(self):
        if self.env.context.get("skip_vendor_number_validation"):
            return
        l10n_do_invoices = self.filtered(
            lambda inv: inv.l10n_latam_country_code == "DO"
                        and inv.l10n_latam_use_documents
                        and inv.l10n_latam_document_type_id
        )

        for rec in l10n_do_invoices:
            has_vat = bool(rec.partner_id.vat and bool(rec.partner_id.vat.strip()))
            l10n_latam_document_type = rec.l10n_latam_document_type_id
            if not has_vat and l10n_latam_document_type.is_vat_required:
                raise ValidationError(
                    _(
                        """El RNC es obligatorio para este tipo de NCF.
                        Por favor, establezca el RNC actual de este cliente. Nombre del contacto: %s""" % rec.partner_id.name
                    )
                )

            elif rec.move_type in ("out_invoice", "out_refund"):
                if (
                        rec.amount_total_signed >= 250000
                        and l10n_latam_document_type.l10n_do_ncf_type[-7:] != "special"
                        and not has_vat
                ):
                    raise UserError(
                        _(
                            "If the invoice amount is greater than RD$250,000.00 "
                            "the customer should have a VAT to validate the invoice"
                        )
                    )

        super(AccountMove, self - l10n_do_invoices)._check_invoice_type_document_type()

    def _get_l10n_do_ecf_modification_code(self):
        """ Return the list of e-CF modification codes required by DGII. """
        return [
            ("1", _("01 - Total Cancellation")),
            ("2", _("02 - Text Correction")),
            ("3", _("03 - Amount correction")),
            ("4", _("04 - NCF replacement issued in contingency")),
            ("5", _("05 - Reference Electronic Consumer Invoice")),
        ]

    is_ecf_invoice = fields.Boolean(
        compute="_compute_is_ecf_invoice",
        store=True,
    )

    l10n_do_ecf_service_env = fields.Selection(related='company_id.l10n_do_ecf_service_env')

    l10n_do_ecf_modification_code = fields.Selection(
        selection="_get_l10n_do_ecf_modification_code",
        string="e-CF Modification Code",
        copy=False,
        readonly=True,
        states={"draft": [("readonly", False)]},
    )



    ecf_numero_factura_interna = fields.Char(string="e-CF Numero de factura interna")

    ecf_numero_pedido_interno = fields.Char(string="e-CF Numero Pedido Interno")

    ecf_fecha_de_entrega = fields.Date(string="e-CF Fecha de Entrega")

    ecf_fecha_orden_de_compra = fields.Date(string="e-CF Fecha Orden de Compra")

    ecf_numero_orden_de_compra = fields.Char(string="e-CF Numero de Orden de Compra")

    ecf_numero_de_contenedor = fields.Char(string="e-CF Numero de Contenedor")

    ecf_numero_de_referencia = fields.Char(string="e-CF Numero de Referencia")

    ecf_emisor_prueba = fields.Many2one('res.partner',string="e-CF Emisor Prueba")

    l10n_do_ecf_service_env = fields.Selection(related="company_id.l10n_do_ecf_service_env")


    l10n_do_ecf_message_status = fields.Char(string="e-CF Status Message", copy=False)

    l10n_do_ecf_sign_date = fields.Datetime(string="e-CF Sign Date", copy=False, readonly=True)

    monto_total_ecf = fields.Float(string="Monto Total ECF para QR", copy=False, readonly=True,store=True)
    l10n_do_electronic_stamp = fields.Char(
        string="Electronic Stamp",
        compute="_compute_l10n_do_electronic_stamp",
        store=True,
    )
    l10n_do_electronic_stamp_url = fields.Char(
        string="Electronic Stamp Url",
        compute="_compute_l10n_do_electronic_stamp",
        store=True,
    )
    l10n_do_company_in_contingency = fields.Boolean(
        string="Company in contingency",
        compute="_compute_company_in_contingency",
    )
    is_l10n_do_internal_sequence = fields.Boolean(
        string="Is internal sequence",
        compute="_compute_l10n_latam_document_type",
        store=True,
    )
    l10n_do_ecf_edi_file = fields.Binary("ECF XML File", copy=False)
    l10n_do_ecf_edi_file_name = fields.Char(
        "ECF XML File Name", copy=False
    )

    l10n_do_ecf_edi_file_fc = fields.Binary("ECF XML File FC", copy=False)
    l10n_do_ecf_edi_file_name_fc = fields.Char(
        "ECF XML File Name FC", copy=False
    )

    @api.depends(
        "l10n_latam_country_code",
        "l10n_latam_document_type_id.l10n_do_ncf_type",
    )
    def _compute_is_ecf_invoice(self):
        for invoice in self:
            invoice.is_ecf_invoice = (
                    invoice.l10n_latam_country_code == "DO"
                    and invoice.l10n_latam_document_type_id
                    and invoice.l10n_latam_document_type_id.l10n_do_ncf_type
                    and invoice.l10n_latam_document_type_id.l10n_do_ncf_type[:2] == "e-"
            )

    @api.depends("state","l10n_latam_available_document_type_ids", "partner_id")
    def _compute_l10n_latam_document_type(self):

        debit_note = self.debit_origin_id
        for rec in self:
            rec.is_l10n_do_internal_sequence = rec.move_type in (
                "out_invoice",
                "out_refund",
            ) or rec.l10n_latam_document_type_id.l10n_do_ncf_type in (
                                                       "minor",
                                                       "informal",
                                                       "exterior",
                                                       "e-minor",
                                                       "e-informal",
                                                       "e-exterior",
                                                   )

        for invoice in self.filtered(lambda x: x.state == 'draft'):


            document_types = invoice.l10n_latam_available_document_type_ids._origin
            document_types = debit_note and document_types.filtered(
                lambda x: x.internal_type == 'debit_note') or document_types
            if invoice.state == 'draft' and invoice.posted_before == False:
                invoice.l10n_latam_document_type_id = document_types and document_types[0].id


    @api.depends("company_id", "company_id.l10n_do_ecf_issuer")
    def _compute_company_in_contingency(self):
        for invoice in self:
            ecf_invoices = self.search(
                [
                    ("is_ecf_invoice", "=", True),
                    ("is_l10n_do_internal_sequence", "=", True),
                ],
                limit=1,
            )
            invoice.l10n_do_company_in_contingency = bool(
                ecf_invoices and not invoice.company_id.l10n_do_ecf_issuer
            )

    def compute_l10n_do_electronic_stamp(self):
        for rec in self:
            rec._compute_l10n_do_electronic_stamp()

    @api.depends("l10n_do_ecf_security_code", "l10n_do_ecf_sign_date", "invoice_date")
    @api.depends_context("l10n_do_ecf_service_env")
    def _compute_l10n_do_electronic_stamp(self):

        l10n_do_ecf_invoice = self.filtered(
            lambda i: i.is_ecf_invoice
                      and i.is_l10n_do_internal_sequence
                      and i.l10n_do_ecf_security_code
        )





        for invoice in l10n_do_ecf_invoice:


            sign_date = invoice.l10n_do_ecf_sign_date

            ecf_service_env = self.company_id.l10n_do_ecf_service_env
            doc_code_prefix = invoice.l10n_latam_document_type_id.doc_code_prefix
            is_rfc = (  # Es un Resumen Factura Consumo
                    doc_code_prefix == "E32" and invoice.amount_total_signed < 250000
            )

            qr_string = "https://%s.dgii.gov.do/%s/ConsultaTimbre%s?" % (
                "fc" if is_rfc else "ecf",
                ecf_service_env,
                "FC" if is_rfc else "",
            )
            qr_string += "RncEmisor=%s&" % invoice.company_id.vat or ""
            if not is_rfc and doc_code_prefix != 'E47':
                qr_string += (
                    "RncComprador=%s&" % invoice.commercial_partner_id.vat
                    if invoice.l10n_latam_document_type_id.doc_code_prefix[1:] != "43"
                    else ''
                )
            qr_string += "ENCF=%s&" % invoice.ref or ""
            if not is_rfc:
                qr_string += "FechaEmision=%s&" % (
                        invoice.invoice_date or fields.Date.today()
                ).strftime("%d-%m-%Y")
            qr_string += "MontoTotal=%s&" % (
                    "{:.2f}".format(abs(invoice.monto_total_ecf))
            ).rstrip("0").rstrip(".")
            if not is_rfc:
                qr_string += "FechaFirma=%s&" % (sign_date).strftime("%d-%m-%Y%%20%H:%M:%S")

            qr_string += "CodigoSeguridad=%s" % urls.url_quote_plus(invoice.l10n_do_ecf_security_code) or ""


            invoice.l10n_do_electronic_stamp = urls.url_quote_plus(qr_string.replace('+','%2B'))

            invoice.l10n_do_electronic_stamp_url = qr_string.replace('+','%2B')

        (self - l10n_do_ecf_invoice).l10n_do_electronic_stamp = False

    def _get_l10n_do_ecf_send_state(self):
        """Returns actual invoice ECF sending status

        - to_send: default state.
        - invalid: sent ecf didn't pass XSD validation.
        - contingency: DGII unreachable by external service. Odoo should send it later
          until delivered accepted state is received.
        - delivered_accepted: expected state that indicate everything is ok with ecf
          issuing.
        - conditionally_accepted: DGII has accepted the ECF but has some remarks
        - delivered_refused: ecf rejected by DGII.
        - not_sent: Odoo have not connection.
        - service_unreachable: external service may be down.

        """
        return [
            ("to_send", _("Not sent")),
            ("invalid", _("Sent, but invalid")),
            ("contingency", _("Contingency")),
            ("delivered_accepted", _("Delivered and accepted")),
            ("conditionally_accepted", _("Conditionally accepted")),
            ("delivered_pending", _("Delivered and pending")),
            ("delivered_refused", _("Delivered and refused")),
            ("not_sent", _("Could not send the e-CF")),
            ("service_unreachable", _("Service unreachable")),
        ]

    l10n_do_ecf_send_state = fields.Selection(
        string="e-CF Send State",
        selection="_get_l10n_do_ecf_send_state",
        copy=False,
        index=True,
        readonly=True,
        default="to_send",
        tracking=True,
    )
    l10n_do_ecf_trackid = fields.Char(
        "e-CF Trackid",
        readonly=True,
        copy=False,
    )
    l10n_do_ecf_security_code = fields.Char(
        states={"draft": [("readonly", False)]},
    )

    l10n_do_ecf_expecting_payment = fields.Boolean(
        string="Payment expected to send ECF",
        compute="_compute_l10n_do_ecf_expecting_payment",
    )


    def _compute_l10n_do_ecf_expecting_payment(self):
        invoices = self.filtered(lambda i: i.move_type != "entry" and i.is_ecf_invoice)
        for invoice in invoices:
            invoice.l10n_do_ecf_expecting_payment = bool(
                not invoice._do_immediate_send()
                and invoice.l10n_do_ecf_send_state == "to_send"
                and invoice.state != "draft"
            )
        (self - invoices).l10n_do_ecf_expecting_payment = False

    def is_l10n_do_partner(self):
        return self.partner_id.country_id and self.partner_id.country_id.code == "DO"

    def is_company_currency(self):
        return self.currency_id == self.company_id.currency_id

    def get_l10n_do_ncf_type(self):
        """
        Indicates if the document Code Type:

        31: Factura de Crédito Fiscal Electrónica
        32: Factura de Consumo Electrónica
        33: Nota de Débito Electrónica
        34: Nota de Crédito Electrónica
        41: Compras Electrónico
        43: Gastos Menores Electrónico
        44: Regímenes Especiales Electrónica
        45: Gubernamental Electrónico
        46: Comprobante para Exportaciones Electrónico
        47: Comprobante para Pagos al Exterior Electrónico
        """

        self.ensure_one()
        return self.l10n_latam_document_type_id.doc_code_prefix[1:]

    def get_payment_type(self):
        """
        Indicates the type of customer payment. Free delivery invoices (code 3)
        are not valid for Crédito Fiscal.

        1 - Al Contado
        2 - Crédito
        3 - Gratuito
        """
        self.ensure_one()
        # TODO: evaluate payment type 3 <Gratuito> Check DGII docs
        if not self.invoice_payment_term_id and self.invoice_date_due:
            if (
                self.invoice_date_due and self.invoice_date
            ) and self.invoice_date_due > self.invoice_date:
                return 2
            else:
                return 1
        elif not self.invoice_payment_term_id:
            return 1
        elif not self.invoice_payment_term_id == self.env.ref(
            "account.account_payment_term_immediate"
        ):
            return 2
        else:
            return 1

    def get_payment_forms(self):

        """
        1: Efectivo
        2: Cheque/Transferencia/Depósito
        3: Tarjeta de Débito/Crédito
        4: Venta a Crédito
        5: Bonos o Certificados de regalo
        6: Permuta
        7: Nota de crédito
        8: Otras Formas de pago

        """

        payment_dict = {
            "cash": "01",
            "bank": "02",
            "card": "03",
            "credit": "04",
            "swap": "06",
            "credit_note": "07",
        }

        payments = []

        for payment in self._get_reconciled_info_JSON_values():
            payment_id = self.env["account.payment"].browse(
                payment.get("account_payment_id")
            )

            payment_amount = payment.get("amount", 0)

            # Convert payment amount to company currency if needed
            if payment.get("currency") != self.company_id.currency_id.symbol:
                currency_id = self.env["res.currency"].search(
                    [("symbol", "=", payment.get("currency")), ('company_id','=',self.company_id.id)], limit=1
                )
                payment_amount = currency_id._convert(
                    payment_amount,
                    self.currency_id,
                    self.company_id,
                    payment.get("date"),
                )

            move_id = False
            if payment_id:
                if payment_id.journal_id.type in ["cash", "bank"]:
                    payment_form = payment_id.journal_id.l10n_do_payment_form
                    if not payment_form:
                        raise ValidationError(
                            _(
                                "Missing *Payment Form* on %s journal"
                                % payment_id.journal_id.name
                            )
                        )
                    payments.append(
                        {
                            "FormaPago": payment_dict[payment_form],
                            "MontoPago": payment_amount,
                        }
                    )

            elif not payment_id:
                move_id = self.env["account.move"].browse(payment.get("move_id"))
                if move_id:
                    payments.append(
                        {
                            "FormaPago": payment_dict["swap"],
                            "MontoPago": payment_amount,
                        }
                    )
            elif not move_id:
                # If invoice is paid, but the payment doesn't come from
                # a journal, assume it is a credit note
                payments.append(
                    {
                        "FormaPago": payment_dict["credit_note"],
                        "MontoPago": payment_amount,
                    }
                )

        return payments

    def _get_IdDoc_data(self,total_pesos):
        """Document Identification values"""
        self.ensure_one()

        l10n_do_ncf_type = self.get_l10n_do_ncf_type()
        itbis_group = self.env.ref("l10n_do.group_itbis")

        fecha_vencimiento = False

        if hasattr(self, 'manual_ncf_expiration_date'):
            if l10n_do_ncf_type not in ("32", "34") and not self.ncf_expiration_date and not self.manual_ncf_expiration_date:
                raise UserError(_("No puede confirmar una factura tipo %s sin antes asignar la fecha de vencimiento.",
                                  l10n_do_ncf_type))
            else:
                if self.manual_ncf_expiration_date:
                    fecha_vencimiento = self.manual_ncf_expiration_date
                else:
                    fecha_vencimiento = self.ncf_expiration_date
        else:
            if l10n_do_ncf_type not in ("32", "34") and not self.ncf_expiration_date:
                raise UserError(_("No puede confirmar una factura tipo %s sin antes asignar la fecha de vencimiento.",
                                  l10n_do_ncf_type))
            else:
                fecha_vencimiento = self.ncf_expiration_date

        # if l10n_do_ncf_type in ("34"):
        #     related_invoice = self.env["account.move"].search([('ref','=',self.l10n_do_origin_ncf),('company_id','=',self.company_id.id)],limit=1)
        #
        #     if round(abs(related_invoice.amount_total_signed),2) < round(abs(self.amount_total_signed),2):
        #         raise UserError(_("No puede confirmar e-NCFs de notas de credio o de debito cuyo monto en DOP sea mayor que la factura original. Monto factura original: %s, Monto de este documento: %s",
        #                           round(abs(related_invoice.amount_total_signed),2), round(abs(self.amount_total_signed),2)))


        id_doc_data = od(
            {
                "TipoeCF": self.get_l10n_do_ncf_type(),
                "eNCF": self.ref,
                "FechaVencimientoSecuencia": dt.strftime(
                    fecha_vencimiento, "%d-%m-%Y"
                ) if l10n_do_ncf_type not in ("32", "34") else False,
            }
        )


        if l10n_do_ncf_type in ("32", "34"):
            del id_doc_data["FechaVencimientoSecuencia"]

        if l10n_do_ncf_type == "34":
            credit_origin_id = self.search(
                [("ref", "=", self.l10n_do_origin_ncf)], limit=1
            )
            credit_invoice_date = credit_origin_id.invoice_date if credit_origin_id else fields.Date.today()
            delta = abs(self.invoice_date - credit_invoice_date)
            id_doc_data["IndicadorNotaCredito"] = int(delta.days > 30)

        if self.company_id.l10n_do_ecf_deferred_submissions:
            id_doc_data["IndicadorEnvioDiferido"] = 1

        if l10n_do_ncf_type not in ("43", "44", "46", "47"):
            if l10n_do_ncf_type == '32' and total_pesos < 250000:
                bool = True
            else:
                if "IndicadorMontoGravado" not in id_doc_data:
                    id_doc_data["IndicadorMontoGravado"] = None
                id_doc_data["IndicadorMontoGravado"] = int(
                    any(
                        True
                        for t in self.invoice_line_ids.tax_ids.filtered(
                            lambda tax: tax.tax_group_id.id == itbis_group.id
                        )
                        if t.price_include
                    )
                )

        if l10n_do_ncf_type not in ("41", "43", "47"):
            if "TipoIngresos" not in id_doc_data:
                id_doc_data["TipoIngresos"] = None
            id_doc_data["TipoIngresos"] = self.l10n_do_income_type

        id_doc_data["TipoPago"] = self.get_payment_type()

        # TODO: actually DGII is not allowing send TablaFormasPago
        # if self.payment_state != "not_paid" and l10n_do_ncf_type not in (
        #     "34",
        #     "43",
        # ):
        #     id_doc_data["TablaFormasPago"] = {"FormaDePago": self.get_payment_forms()}

        if self.invoice_date_due and l10n_do_ncf_type == '32' and total_pesos < 250000:
            bool = True
        elif (
            self.invoice_date_due
            and (id_doc_data["TipoPago"] == 2 or id_doc_data["TipoPago"] == '2')
            and l10n_do_ncf_type != "43"
        ):
            id_doc_data["FechaLimitePago"] = dt.strftime(
                self.invoice_date_due, "%d-%m-%Y"
            )

            if l10n_do_ncf_type not in ("34", "43"):
                delta = self.invoice_date_due - self.invoice_date
                id_doc_data["TerminoPago"] = "%s dias" % delta.days

        return id_doc_data

    def _get_Emisor_data(self,total_pesos):
        """Issuer (company) values"""
        self.ensure_one()
        l10n_do_ncf_type = self.get_l10n_do_ncf_type()

        if not self.ecf_emisor_prueba:

            if l10n_do_ncf_type == '32' and total_pesos < 250000:
                issuer_data = od(
                    {
                        "RNCEmisor": self.company_id.vat,
                        "RazonSocialEmisor": self.company_id.name,
                        "FechaEmision": dt.strftime(self.invoice_date, "%d-%m-%Y") or fields.Date.today(),
                    }
                )

            else:
                issuer_data = od(
                    {
                        "RNCEmisor": self.company_id.vat,
                        "RazonSocialEmisor": self.company_id.name,
                        "NombreComercial": self.company_id.name,
                        "DireccionEmisor": "",
                    }
                )

            if not self.company_id.street or not len(str(self.company_id.street).strip()):
                action = self.env.ref("base.action_res_company_form")
                msg = _("Cannot send an ECF if company has no address.")
                raise RedirectWarning(msg, action.id, _("Go to Companies"))

            if l10n_do_ncf_type == '32' and total_pesos < 250000:
                bool = True

                if self.company_id.partner_id.municipio_ecf != False:
                    issuer_data["Municipio"] = self.company_id.partner_id.municipio_ecf

                if self.company_id.partner_id.provincia_ecf != False:
                    issuer_data["Provincia"] = self.company_id.partner_id.provincia_ecf


                issuer_data["FechaEmision"] = dt.strftime(self.invoice_date, "%d-%m-%Y") or fields.Date.today()
            else:
                issuer_data["DireccionEmisor"] = self.company_id.street

                if self.company_id.partner_id.municipio_ecf != False:
                    issuer_data["Municipio"] = self.company_id.partner_id.municipio_ecf

                if self.company_id.partner_id.provincia_ecf != False:
                    issuer_data["Provincia"] = self.company_id.partner_id.provincia_ecf


                # if self.company_id.partner_id.phone != False or self.company_id.partner_id.mobile != False:
                #     issuer_data["TablaTelefonoEmisor"] = {}
                #     if self.company_id.partner_id.phone != False:
                #         issuer_data["TablaTelefonoEmisor"]["TelefonoEmisor"] =self.company_id.partner_id.phone
                #     if self.company_id.partner_id.mobile != False:
                #         issuer_data["TablaTelefonoEmisor"]["TelefonoEmisor"] = self.company_id.partner_id.mobile

                if self.company_id.partner_id.email != False:
                    issuer_data["CorreoEmisor"] = self.company_id.partner_id.email


                if self.company_id.partner_id.website != False:
                    issuer_data["WebSite"] = self.company_id.partner_id.website.replace("http://","")

                if self.user_id.partner_id.codigo_vendedor_ecf != False and self.move_type not in ('in_invoice','in_refund'):
                    issuer_data["CodigoVendedor"] = self.user_id.partner_id.codigo_vendedor_ecf

                issuer_data["NumeroFacturaInterna"] = self.name if self.ecf_numero_factura_interna == False else self.ecf_numero_factura_interna

                # issuer_data["NumeroPedidoInterno"] = self.invoice_origin if self.ecf_numero_pedido_interno == False else self.ecf_numero_pedido_interno

                # if self.company_id.partner_id.street2 != False and self.move_type not in ('in_invoice','in_refund'):
                #     issuer_data["ZonaVenta"] = self.company_id.partner_id.street2

                issuer_data["FechaEmision"] = dt.strftime(self.invoice_date, "%d-%m-%Y") or fields.Date.today()

        else:

            if l10n_do_ncf_type == '32' and total_pesos < 250000:
                issuer_data = od(
                    {
                        "RNCEmisor": self.ecf_emisor_prueba.vat,
                        "RazonSocialEmisor": self.ecf_emisor_prueba.name,
                        "FechaEmision": dt.strftime(self.invoice_date, "%d-%m-%Y") or fields.Date.today(),
                    }
                )

            else:
                issuer_data = od(
                    {
                        "RNCEmisor": self.ecf_emisor_prueba.vat,
                        "RazonSocialEmisor": self.ecf_emisor_prueba.name,
                        "NombreComercial": self.ecf_emisor_prueba.name,
                        "DireccionEmisor": "",
                    }
                )

            if not self.ecf_emisor_prueba.street or not len(str(self.ecf_emisor_prueba.street).strip()):
                action = self.env.ref("base.action_res_company_form")
                msg = _("Cannot send an ECF if company has no address.")
                raise RedirectWarning(msg, action.id, _("Go to Companies"))

            if l10n_do_ncf_type == '32' and total_pesos < 250000:
                bool = True

                if self.ecf_emisor_prueba.municipio_ecf != False:
                    issuer_data["Municipio"] = self.ecf_emisor_prueba.municipio_ecf

                if self.ecf_emisor_prueba.provincia_ecf != False:
                    issuer_data["Provincia"] = self.ecf_emisor_prueba.provincia_ecf


                issuer_data["FechaEmision"] = dt.strftime(self.invoice_date, "%d-%m-%Y") or fields.Date.today()
            else:
                issuer_data["DireccionEmisor"] = self.ecf_emisor_prueba.street

                if self.ecf_emisor_prueba.municipio_ecf != False:
                    issuer_data["Municipio"] = self.ecf_emisor_prueba.municipio_ecf

                if self.ecf_emisor_prueba.provincia_ecf != False:
                    issuer_data["Provincia"] = self.ecf_emisor_prueba.provincia_ecf

                # if self.ecf_emisor_prueba.phone != False or self.ecf_emisor_prueba.mobile != False:
                #     issuer_data["TablaTelefonoEmisor"] = {}
                #     if self.ecf_emisor_prueba.phone != False:
                #         issuer_data["TablaTelefonoEmisor"]["TelefonoEmisor"] = self.ecf_emisor_prueba.phone
                #     if self.ecf_emisor_prueba.mobile != False:
                #         issuer_data["TablaTelefonoEmisor"]["TelefonoEmisor"] = self.ecf_emisor_prueba.mobile

                if self.ecf_emisor_prueba.email != False:
                    issuer_data["CorreoEmisor"] = self.ecf_emisor_prueba.email

                if self.ecf_emisor_prueba.website != False:
                    issuer_data["WebSite"] = self.ecf_emisor_prueba.website.replace("http://", "")

                if self.user_id.partner_id.codigo_vendedor_ecf != False and self.move_type not in ('in_invoice','in_refund'):
                    issuer_data["CodigoVendedor"] = self.user_id.partner_id.codigo_vendedor_ecf

                issuer_data[
                        "NumeroFacturaInterna"] = self.name if self.ecf_numero_factura_interna == False else self.ecf_numero_factura_interna

                # issuer_data[
                #         "NumeroPedidoInterno"] = self.invoice_origin if self.ecf_numero_pedido_interno == False else self.ecf_numero_pedido_interno

                # if self.ecf_emisor_prueba.street2 != False:
                #     issuer_data["ZonaVenta"] = self.ecf_emisor_prueba.street2

                issuer_data["FechaEmision"] = dt.strftime(self.invoice_date, "%d-%m-%Y") or fields.Date.today()

        # raise UserError(_("%s", issuer_data))

        return issuer_data

    def _get_Comprador_data(self,total_pesos):
        """Buyer (invoice partner) values """
        self.ensure_one()
        l10n_do_ncf_type = self.get_l10n_do_ncf_type()
        partner_vat = self.partner_id.vat or ""
        is_l10n_do_partner = self.is_l10n_do_partner()

        if self.partner_id.vat:
            if "-" in self.partner_id.vat:
                self.partner_id.vat = self.partner_id.vat.replace("-","")

        buyer_data = od({})
        if l10n_do_ncf_type not in ("43", "47"):

            if l10n_do_ncf_type in ("31", "41", "45","33"):
                buyer_data["RNCComprador"] = partner_vat.replace("-","")

            if l10n_do_ncf_type == "32" and partner_vat:
                buyer_data["RNCComprador"] = partner_vat.replace("-","")

            if l10n_do_ncf_type in ("33", "34"):
                if (
                    self.debit_origin_id
                    and self.debit_origin_id.get_l10n_do_ncf_type != "32"
                    or (
                        self.debit_origin_id.get_l10n_do_ncf_type == "32"
                        and self.debit_origin_id.amount_total_signed >= 250000
                    )
                    or self.move_type in ("out_refund", "in_refund")
                ):
                    if is_l10n_do_partner and partner_vat:
                        buyer_data["RNCComprador"] = partner_vat.replace("-","")
                    elif partner_vat:
                        buyer_data["IdentificadorExtranjero"] = partner_vat.replace("-","")

            if l10n_do_ncf_type in ("44","46"):
                if is_l10n_do_partner and partner_vat:
                    buyer_data["RNCComprador"] = partner_vat.replace("-","")
                elif not is_l10n_do_partner and partner_vat:
                    buyer_data["IdentificadorExtranjero"] = partner_vat.replace("-","")

            if self.company_id.partner_id.l10n_do_dgii_tax_payer_type == "special":
                if is_l10n_do_partner:
                    buyer_data["RNCComprador"] = partner_vat.replace("-","")
                else:
                    buyer_data["IdentificadorExtranjero"] = partner_vat.replace("-","")

        if l10n_do_ncf_type not in ("31", "41", "43", "45") and not is_l10n_do_partner:

            if l10n_do_ncf_type == "32" and total_pesos >= 250000:
                buyer_data["IdentificadorExtranjero"] = partner_vat.replace("-","")
            elif l10n_do_ncf_type == "46":
                buyer_data["IdentificadorExtranjero"] = partner_vat.replace("-","")

        if l10n_do_ncf_type not in ("43", "47"):

            # TODO: are those If really needed?
            if l10n_do_ncf_type == "32":
                if total_pesos >= 250000 or partner_vat:
                    buyer_data["RazonSocialComprador"] = self.commercial_partner_id.name

            if l10n_do_ncf_type in ("33", "34"):
                buyer_data["RazonSocialComprador"] = self.commercial_partner_id.name

            else:  # 31, 41, 44, 45, 46
                buyer_data["RazonSocialComprador"] = self.commercial_partner_id.name

        if l10n_do_ncf_type == '32' and total_pesos < 250000:
            bool = True

            # if self.partner_id.phone != False:
            #     buyer_data["ContactoComprador"] = self.partner_id.phone

            # if self.partner_id.street != False:
            #     buyer_data["DireccionComprador"] = self.partner_id.street

            if self.partner_id.municipio_ecf != False:
                buyer_data["MunicipioComprador"] = self.partner_id.municipio_ecf

            if self.partner_id.provincia_ecf != False:
                buyer_data["ProvinciaComprador"] = self.partner_id.provincia_ecf

            if self.ecf_fecha_de_entrega != False:
                buyer_data["FechaEntrega"] = dt.strftime(self.ecf_fecha_de_entrega, "%d-%m-%Y")
            if self.ecf_fecha_orden_de_compra != False:
                buyer_data["FechaOrdenCompra"] = dt.strftime(self.ecf_fecha_orden_de_compra, "%d-%m-%Y")

            if self.ecf_numero_orden_de_compra != False:
                buyer_data["NumeroOrdenCompra"] = self.ecf_numero_orden_de_compra

            if self.partner_id.ref != False:
                boole = True
                # buyer_data["CodigoInternoComprador"] = self.partner_id.ref

        else:
            if self.partner_id.phone != False:
                buyer_data["ContactoComprador"] = self.partner_id.phone


            if self.partner_id.email != False:
                buyer_data["CorreoComprador"] = self.partner_id.email

            if self.partner_id.street != False:
                buyer_data["DireccionComprador"] = self.partner_id.street

            if self.partner_id.municipio_ecf != False:
                buyer_data["MunicipioComprador"] = self.partner_id.municipio_ecf

            if self.partner_id.provincia_ecf != False:
                buyer_data["ProvinciaComprador"] = self.partner_id.provincia_ecf

            if self.ecf_fecha_de_entrega != False:
                buyer_data["FechaEntrega"] = dt.strftime(self.ecf_fecha_de_entrega, "%d-%m-%Y")
            if self.ecf_fecha_orden_de_compra != False:
                buyer_data["FechaOrdenCompra"] = dt.strftime(self.ecf_fecha_orden_de_compra, "%d-%m-%Y")

            if self.ecf_numero_orden_de_compra != False:
                buyer_data["NumeroOrdenCompra"] = self.ecf_numero_orden_de_compra

            if self.partner_id.ref != False:
                # buyer_data["CodigoInternoComprador"] = self.partner_id.ref
                boole = True
        return buyer_data

    def get_taxed_amount_data(self):
        """ITBIS taxed amount
        According to the DGII, there are three types of
        amounts taxed by ITBIS:

        18% -- Most common
        16% -- Used on 'healthy products' like Yogurt, coffee and so on.
        0% -- Should be used on exported products

        See Law No. 253-12, art. 343 of dominican Tributary Code for further info
        """

        itbis_data = {
            "total_taxed_amount": 0,
            "18_taxed_base": 0,
            "18_taxed_amount": 0,
            "16_taxed_base": 0,
            "16_taxed_amount": 0,
            "0_taxed_base": 0,
            "0_taxed_amount": 0,
            "exempt_amount": 0,
            "itbis_withholding_amount": 0,
            "isr_withholding_amount": 0,
        }

        tax_data = [
            line.tax_ids.compute_all(
                price_unit=line.price_unit * (1 - (line.discount / 100.0)),
                currency=line.currency_id,
                product=line.product_id,
                partner=line.move_id.partner_id,
                quantity=line.quantity
            )
            for line in self.invoice_line_ids
        ]
        l10n_do_ncf_type = self.get_l10n_do_ncf_type()
        for line in self.invoice_line_ids:
            if not line.tax_ids:
                type_tax = 'sale' if line.move_id.move_type in ('out_invoice','out_refund') else 'purchase'
                exempt_tax = self.env['account.tax'].search([('amount', '=', 0), ('type_tax_use', '=', type_tax),
                                                             ('amount_type', '!=', 'group'),
                                                             ('company_id', '=', line.company_id.id),
                                                             ('description', '=', 'Exento')], limit=1)
                line.write({'tax_ids':[(6,0,exempt_tax.ids)]})

            for tax in line.tax_ids:
                if l10n_do_ncf_type == "43" and tax.amount != 0.0:
                    raise UserError(_("No puede emitir un e-NCF de gasto menor con algun impuesto asignado que no sea igual a 0 o exento. Linea: %s", line.name))
            test = len(str(line.price_unit)[str(line.price_unit).find('.')+1:len(str(line.price_unit))])
            if len(str(line.price_unit)[str(line.price_unit).find('.')+1:len(str(line.price_unit))]) > 4:
                decimales = self.env['decimal.precision'].sudo().search([('name', '=', 'Product Price')]).digits
                precision = decimales if decimales <= 4 else 4
                line.price_unit = round(line.price_unit,precision)
                # raise UserError(
                #     _("No puede tener un precio con mas de 4 decimales, pues la DGII no los acepta para los e-NCF. Redondear como mucho a 4 decimales. Linea: %s", line.name))

        itbis_data["total_taxed_amount"] = sum(
            line["total_excluded"] for line in tax_data
        )

        # raise UserError(_("%s", tax_data))

        for line_taxes in tax_data:
            for tax in line_taxes["taxes"]:
                if not tax["amount"] and not l10n_do_ncf_type in ("46"):
                    itbis_data["exempt_amount"] += tax["base"]

                tax_id = self.env["account.tax"].browse(tax["id"])
                if tax_id.amount == 18:
                    itbis_data["18_taxed_base"] += tax["base"]
                    itbis_data["18_taxed_amount"] += tax["amount"]
                elif tax_id.amount == 16:
                    itbis_data["16_taxed_base"] += tax["base"]
                    itbis_data["16_taxed_amount"] += tax["amount"]
                elif tax_id.amount == 0 and l10n_do_ncf_type in ("46"):
                    itbis_data["0_taxed_base"] += tax["base"]
                    itbis_data["0_taxed_amount"] += tax["amount"]
                elif tax_id.amount < 0 and 'ITBIS' in str(tax_id.tax_group_id.name):
                    itbis_data["itbis_withholding_amount"] += tax["amount"]
                elif tax_id.amount < 0 and 'ISR' in str(tax_id.tax_group_id.name):
                    itbis_data["isr_withholding_amount"] += tax["amount"]

                if tax_id.ecf_tipo_impuesto:

                    if "ImpuestosAdicionales" not in itbis_data:
                        tax_amount = (tax_id.amount/100) * tax["base"] if tax_id.amount_type == 'percent' else tax["amount"]
                        itbis_data["ImpuestosAdicionales"] = {}

                        if not tax_id.ecf_otro_tipo_impuesto and (tax_id.ecf_monto_impuesto_selectivo_consumo_especifico > 0 or tax_id.ecf_monto_impuesto_selectivo_consumo_advalorem > 0):
                            if tax_id.amount > 0 and tax_id.ecf_monto_impuesto_selectivo_consumo_especifico > 0:

                                itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto] = {"tipo_impuesto": tax_id.ecf_tipo_impuesto,
                                                                        "tasa": tax_id.amount,
                                                                        "cantidad": sum(
                                                                            line.quantity for line
                                                                            in self.invoice_line_ids.filtered(lambda x: tax_id.id in x.tax_ids.ids)
                                                                        ),
                                                                        "ecf_monto_impuesto_selectivo_consumo_especifico": tax_id.ecf_monto_impuesto_selectivo_consumo_especifico,}

                            if tax_id.amount > 0 and tax_id.ecf_monto_impuesto_selectivo_consumo_advalorem > 0:
                                itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto] = {"tipo_impuesto": tax_id.ecf_tipo_impuesto,
                                                                        "tasa": tax_id.amount,
                                                                        "cantidad": sum(
                                                                            line.quantity for line in self.invoice_line_ids.filtered(lambda x: tax_id.id in x.tax_ids.ids)
                                                                        ),
                                                                        "ecf_monto_impuesto_selectivo_consumo_advalorem": tax_id.ecf_monto_impuesto_selectivo_consumo_advalorem}
                        else:
                            itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto] = {
                                "tipo_impuesto": tax_id.ecf_tipo_impuesto,
                                "tasa": tax_id.amount,
                                "cantidad": sum(
                                    line.quantity for line in
                                    self.invoice_line_ids.filtered(lambda x: tax_id.id in x.tax_ids.ids)
                                ),
                                "ecf_otro_tipo_impuesto": tax_amount if tax_amount > 0 else 0}


                    else:
                        tax_amount = (tax_id.amount/100) * tax["base"] if tax_id.amount_type == 'percent' else tax["amount"]

                        if tax_id.ecf_tipo_impuesto in itbis_data["ImpuestosAdicionales"]:
                            if not tax_id.ecf_otro_tipo_impuesto and (tax_id.ecf_monto_impuesto_selectivo_consumo_especifico > 0 or tax_id.ecf_monto_impuesto_selectivo_consumo_advalorem > 0):
                                if tax_id.ecf_monto_impuesto_selectivo_consumo_especifico > 0:
                                    itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto]["ecf_monto_impuesto_selectivo_consumo_especifico"] += tax_id.ecf_monto_impuesto_selectivo_consumo_especifico
                                if tax_id.ecf_monto_impuesto_selectivo_consumo_especifico > 0:
                                    itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto][
                                        "ecf_monto_impuesto_selectivo_consumo_advalorem"] += tax_id.ecf_monto_impuesto_selectivo_consumo_advalorem
                            else:
                                itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto][
                                    "ecf_otro_tipo_impuesto"] += tax_amount if tax_amount > 0 else 0

                        elif not tax_id.ecf_otro_tipo_impuesto and (
                                tax_id.ecf_monto_impuesto_selectivo_consumo_especifico > 0 or tax_id.ecf_monto_impuesto_selectivo_consumo_advalorem > 0):
                            if tax_id.amount > 0 and tax_id.ecf_monto_impuesto_selectivo_consumo_especifico > 0:
                                itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto] = {
                                    "tipo_impuesto": tax_id.ecf_tipo_impuesto,
                                    "tasa": tax_id.amount,
                                    "cantidad": sum(
                                        line.quantity for line
                                        in self.invoice_line_ids.filtered(lambda x: tax_id.id in x.tax_ids.ids)
                                    ),
                                    "ecf_monto_impuesto_selectivo_consumo_especifico": tax_id.ecf_monto_impuesto_selectivo_consumo_especifico, }

                            if tax_id.amount > 0 and tax_id.ecf_monto_impuesto_selectivo_consumo_advalorem > 0:
                                itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto] = {
                                    "tipo_impuesto": tax_id.ecf_tipo_impuesto,
                                    "tasa": tax_id.amount,
                                    "cantidad": sum(
                                        line.quantity for line in
                                        self.invoice_line_ids.filtered(lambda x: tax_id.id in x.tax_ids.ids)
                                    ),
                                    "ecf_monto_impuesto_selectivo_consumo_advalorem": tax_id.ecf_monto_impuesto_selectivo_consumo_advalorem}
                        else:
                            itbis_data["ImpuestosAdicionales"][tax_id.ecf_tipo_impuesto] = {
                                "tipo_impuesto": tax_id.ecf_tipo_impuesto,
                                "tasa": tax_id.amount,
                                "cantidad": sum(
                                    line.quantity for line in
                                    self.invoice_line_ids.filtered(lambda x: tax_id.id in x.tax_ids.ids)
                                ),
                                "ecf_otro_tipo_impuesto": tax_amount if tax_amount > 0 else 0}



        if self.withholded_itbis > 0:
            itbis_data["itbis_withholding_amount"] += self.withholded_itbis

        if self.income_withholding > 0:
            itbis_data["isr_withholding_amount"] += self.income_withholding


        return itbis_data

    def _get_Totales_data(self,total_pesos=0.0):
        """Invoice amounts related values"""
        self.ensure_one()

        monto_total_ecf = 0.0

        totals_data = od({})
        tax_data = self.get_taxed_amount_data()
        l10n_do_ncf_type = self.get_l10n_do_ncf_type()
        is_company_currency = self.is_company_currency()

        total_adicional_impuestos = 0.0
        impuestos_adicionales = []

        total_itbis_asiento_18 = 0.0
        total_itbis_asiento_16 = 0.0

        monto_itbis_retenido = 0.0
        monto_isr_retenido = 0.0

        has_manual_retentions = hasattr(self.env['account.move.line'],'monto_itbis_retenido') and hasattr(self.env['account.move.line'],'monto_isr_retenido')

        if has_manual_retentions:
            monto_itbis_retenido = abs(sum([l.monto_itbis_retenido for l in self.invoice_line_ids]))
            monto_isr_retenido = abs(sum([l.monto_isr_retenido for l in self.invoice_line_ids]))

        for l in self.line_ids.filtered(lambda x: x.tax_line_id != False):
            if l.tax_line_id.amount == 18.0:
                total_itbis_asiento_18 += abs(l.amount_currency)
            if l.tax_line_id.amount == 16.0:
                total_itbis_asiento_16 += abs(l.amount_currency)

        diff_18 = round(total_itbis_asiento_18 - tax_data["18_taxed_amount"],4)
        diff_16 = round(total_itbis_asiento_16 - tax_data["16_taxed_amount"],4)
        # diff_total = (tax_data["18_taxed_base"]+tax_data["16_taxed_base"]+tax_data["0_taxed_base"]) - abs(self.amount_untaxed_signed)

        tax_data["18_taxed_amount"] += diff_18
        tax_data["16_taxed_amount"] += diff_16

        base_18 = round(tax_data["18_taxed_amount"] / 0.18,2)
        base_16 = round(tax_data["16_taxed_amount"] / 0.16,2)


        diff_gravado_18 = tax_data["18_taxed_base"] - base_18
        diff_gravado_16 = tax_data["16_taxed_base"] - base_16

        tax_data["18_taxed_base"] -= diff_gravado_18
        tax_data["16_taxed_base"] -= diff_gravado_16

        monto_exento = 0
        if tax_data["exempt_amount"]:
            monto_exento = abs(round(tax_data["exempt_amount"], 2))

        if "ImpuestosAdicionales" in tax_data:
            for f, v in tax_data["ImpuestosAdicionales"].items():

                if "ecf_monto_impuesto_selectivo_consumo_especifico" in v:
                    if v["ecf_monto_impuesto_selectivo_consumo_especifico"] > 0:
                        total_adicional_impuestos += v["ecf_monto_impuesto_selectivo_consumo_especifico"]
                        impuestos_adicionales.append({"ImpuestoAdicional":{"TipoImpuesto": f, "TasaImpuestoAdicional": "{:.2f}".format(round(v[
                                                          "tasa"],2)),
                                                      "MontoImpuestoSelectivoConsumoEspecifico": "{:.2f}".format(round(v["ecf_monto_impuesto_selectivo_consumo_especifico"],2)), }})
                if "ecf_monto_impuesto_selectivo_consumo_advalorem" in v:
                    if v["ecf_monto_impuesto_selectivo_consumo_advalorem"] > 0:
                        total_adicional_impuestos += v["ecf_monto_impuesto_selectivo_consumo_advalorem"]
                        impuestos_adicionales.append({"ImpuestoAdicional":{"TipoImpuesto": f, "TasaImpuestoAdicional": "{:.0f}".format(round(v["tasa"],0)),
                                                      "MontoImpuestoSelectivoConsumoAdvalorem": "{:.2f}".format(round(v["ecf_monto_impuesto_selectivo_consumo_advalorem"],2)), }})

                if "ecf_otro_tipo_impuesto" in v:
                    if v["ecf_otro_tipo_impuesto"] > 0:
                        total_adicional_impuestos += v["ecf_otro_tipo_impuesto"]
                        impuestos_adicionales.append({"ImpuestoAdicional":{"TipoImpuesto": f, "TasaImpuestoAdicional": "{:.0f}".format(round(v[
                                                          "tasa"],0)),
                                                      "OtrosImpuestosAdicionales": "{:.2f}".format(round(v["ecf_otro_tipo_impuesto"],2)), }})


            if impuestos_adicionales != []:
                if "MontoGravadoTotal":
                    totals_data["MontoGravadoTotal"] = "{:.2f}".format(abs(round(float(totals_data["MontoGravadoTotal"]), 2)))
                if "MontoGravadoI1":
                    totals_data["MontoGravadoI1"] = "{:.2f}".format(
                        abs(round(float(totals_data["MontoGravadoI1"]), 2)))

                totals_data["MontoImpuestoAdicional"] = "{:.2f}".format(abs(round(total_adicional_impuestos,2)))
                totals_data["ImpuestosAdicionales"] = impuestos_adicionales



        total_taxed = sum(
            [
                tax_data["18_taxed_base"],
                tax_data["16_taxed_base"],
                tax_data["0_taxed_base"],
            ]
        )
        total_itbis = sum(
            [
                tax_data["18_taxed_amount"]  ,
                tax_data["16_taxed_amount"],
                tax_data["0_taxed_amount"],
            ]
        )

        monto_total = abs(round(total_taxed + total_itbis + monto_exento + total_adicional_impuestos, 2))
        diff_total = round(abs(self.amount_total_signed) - monto_total,2)

        if abs(diff_total) >= 0.01 and abs(diff_total) <= 0.10 and total_taxed > 0.0:
            total_taxed += diff_total
            if tax_data["18_taxed_base"] > 0.10:
                tax_data["18_taxed_base"] += diff_total
            elif tax_data["16_taxed_base"] > 0.10:
                tax_data["16_taxed_base"] += diff_total




        if l10n_do_ncf_type in ("44","46","47","43") and total_itbis > 0:
            raise UserError(_("No puede confirmar una factura de regimen especial, gasto menor o extranjero cuando las mismas contiene ITBIS. "
                              "Favor asignar el tipo de impuesto 'EXENTO ITBIS EN VENTA' para que la factura pueda confirmarse. %s", total_taxed))



        if l10n_do_ncf_type not in ("44","47","43") and total_itbis > 0:
            if total_taxed:
                totals_data["MontoGravadoTotal"] = "{:.2f}".format(abs(round(total_taxed, 2)))
            if tax_data["18_taxed_base"]:
                totals_data["MontoGravadoI1"] = "{:.2f}".format(abs(round(tax_data["18_taxed_base"], 2)))
            if tax_data["16_taxed_base"]:
                totals_data["MontoGravadoI2"] = "{:.2f}".format(abs(round(tax_data["16_taxed_base"], 2)))
            if tax_data["0_taxed_base"]:
                totals_data["MontoGravadoI3"] = "{:.2f}".format(abs(round(tax_data["0_taxed_base"], 2)))
            if tax_data["exempt_amount"]:
                totals_data["MontoExento"] = "{:.2f}".format(abs(round(tax_data["exempt_amount"], 2)))

            if tax_data["18_taxed_base"] and not (l10n_do_ncf_type == '32' and total_pesos < 250000):
                totals_data["ITBIS1"] = "18"
            if tax_data["16_taxed_base"] and not (l10n_do_ncf_type == '32' and total_pesos < 250000):
                totals_data["ITBIS2"] = "16"
            if tax_data["0_taxed_base"] and not (l10n_do_ncf_type == '32' and total_pesos < 250000):
                totals_data["ITBIS3"] = "0"
            if total_taxed:
                totals_data["TotalITBIS"] = "{:.2f}".format(abs(round(total_itbis, 2)))
            if tax_data["18_taxed_base"]:
                totals_data["TotalITBIS1"] = "{:.2f}".format(abs(round(tax_data["18_taxed_amount"], 2)))
            if tax_data["16_taxed_base"]:
                totals_data["TotalITBIS2"] = "{:.2f}".format(abs(round(tax_data["16_taxed_amount"], 2)))
            if tax_data["0_taxed_base"]:
                totals_data["TotalITBIS3"] = "{:.2f}".format(abs(round(tax_data["0_taxed_amount"], 2)))
        else:

            if l10n_do_ncf_type in ("46"):
                if total_taxed:
                    totals_data["MontoGravadoTotal"] = "{:.2f}".format(abs(round(total_taxed, 2)))
                if tax_data["18_taxed_base"]:
                    totals_data["MontoGravadoI1"] = "{:.2f}".format(abs(round(tax_data["18_taxed_base"], 2)))
                if tax_data["16_taxed_base"]:
                    totals_data["MontoGravadoI2"] = "{:.2f}".format(abs(round(tax_data["16_taxed_base"], 2)))
                if tax_data["0_taxed_base"]:
                    totals_data["MontoGravadoI3"] = "{:.2f}".format(abs(round(tax_data["0_taxed_base"], 2)))

                if tax_data["18_taxed_base"] and not (l10n_do_ncf_type == '32' and total_pesos < 250000):
                    totals_data["ITBIS1"] = "18"
                if tax_data["16_taxed_base"] and not (l10n_do_ncf_type == '32' and total_pesos < 250000):
                    totals_data["ITBIS2"] = "16"
                if tax_data["0_taxed_base"] and not (l10n_do_ncf_type == '32' and total_pesos < 250000):
                    totals_data["ITBIS3"] = "0"
                if total_taxed:
                    totals_data["TotalITBIS"] = "{:.2f}".format(abs(round(total_itbis, 2)))
                if tax_data["18_taxed_base"]:
                    totals_data["TotalITBIS1"] = "{:.2f}".format(abs(round(tax_data["18_taxed_amount"], 2)))
                if tax_data["16_taxed_base"]:
                    totals_data["TotalITBIS2"] = "{:.2f}".format(abs(round(tax_data["16_taxed_amount"], 2)))
                if tax_data["0_taxed_base"]:
                    totals_data["TotalITBIS3"] = "{:.2f}".format(abs(round(tax_data["0_taxed_amount"], 2)))

            else:
                if tax_data["exempt_amount"]:
                    totals_data["MontoExento"] = "{:.2f}".format(abs(round(tax_data["exempt_amount"], 2)))




        if l10n_do_ncf_type not in ("43", "44") and total_taxed:
            if l10n_do_ncf_type == '32' and total_pesos < 250000:
                totals_data["MontoTotal"] = "{:.2f}".format(abs(round(total_taxed + total_itbis + monto_exento + total_adicional_impuestos, 2)))
                monto_total_ecf = abs(round(total_taxed + total_itbis + monto_exento + total_adicional_impuestos, 2))
            else:
                totals_data["MontoTotal"] = "{:.2f}".format(abs(round(total_taxed + total_itbis + monto_exento + total_adicional_impuestos, 2)))
                monto_total_ecf = abs(round(total_taxed + total_itbis + monto_exento + total_adicional_impuestos, 2))
        else:
            if l10n_do_ncf_type == '32' and total_pesos < 250000:
                totals_data["MontoTotal"] = "{:.2f}".format(abs(round(self.amount_total, 2)))
                monto_total_ecf = abs(round(self.amount_total, 2))
            else:
                totals_data["MontoTotal"] = "{:.2f}".format(abs(round(self.amount_total, 2)))
                monto_total_ecf = abs(round(self.amount_total, 2))

        if l10n_do_ncf_type not in ("43", "44"):

            if l10n_do_ncf_type in ("41"):
                if monto_itbis_retenido > 0:
                    totals_data["TotalITBISRetenido"] = "{:.2f}".format(abs(
                        round(monto_itbis_retenido, 2)
                    ))
                else:
                    totals_data["TotalITBISRetenido"] = "{:.2f}".format(abs(
                        round(tax_data["itbis_withholding_amount"], 2)
                    ))
                if monto_isr_retenido > 0:
                    totals_data["TotalISRRetencion"] = "{:.2f}".format(abs(
                        round(monto_isr_retenido, 2)
                    ))
                else:
                    totals_data["TotalISRRetencion"] = "{:.2f}".format(abs(
                        round(tax_data["isr_withholding_amount"], 2)
                    ))
            if l10n_do_ncf_type in ("47"):
                if monto_isr_retenido > 0:
                    totals_data["TotalISRRetencion"] = "{:.2f}".format(abs(
                        round(monto_isr_retenido, 2)
                    ))
                else:
                    totals_data["TotalISRRetencion"] = "{:.2f}".format(abs(
                        round(tax_data["isr_withholding_amount"], 2)
                    ))
            if l10n_do_ncf_type not in ("41") and abs(
                    round(tax_data["itbis_withholding_amount"], 2)
                ) > 0:
                if monto_itbis_retenido > 0:
                    totals_data["TotalITBISRetenido"] = "{:.2f}".format(abs(
                        round(monto_itbis_retenido, 2)
                    ))
                else:
                    totals_data["TotalITBISRetenido"] = "{:.2f}".format(abs(
                        round(tax_data["itbis_withholding_amount"], 2)
                    ))
            if l10n_do_ncf_type not in ("41") and abs(
                    round(tax_data["isr_withholding_amount"], 2)
                ) > 0:
                if monto_isr_retenido > 0:
                    totals_data["TotalISRRetencion"] = "{:.2f}".format(abs(
                        round(monto_isr_retenido, 2)
                    ))
                else:
                    totals_data["TotalISRRetencion"] = "{:.2f}".format(abs(
                        round(tax_data["isr_withholding_amount"], 2)
                    ))

        if not is_company_currency:
            rate = abs(round(1 / (self.amount_total / self.amount_total_signed), 4))
            monto_total_ecf = round(rate * monto_total_ecf,2)
            totals_data = od(
                {
                    f: "{:.2f}".format(round(float(v) * rate, 2)) if not "ITBIS1" == f and not "ITBIS2" == f and not "ITBIS3" == f else v
                    for f, v in totals_data.items()
                }
            )

        # raise UserError(_("%s", totals_data))

        return monto_total_ecf,totals_data

    def _get_OtraMoneda_data(self, ecf_object_data):
        """Only used if invoice currency is not company currency"""
        self.ensure_one()
        l10n_do_ncf_type = self.get_l10n_do_ncf_type()
        currency_data = od({})

        currency_data["TipoMoneda"] = self.currency_id.name
        currency_data["TipoCambio"] = abs(
            round(1 / (self.amount_total / self.amount_total_signed), 4)
        )

        rate = currency_data["TipoCambio"]

        if l10n_do_ncf_type not in ("43", "44", "47"):

            if "MontoGravadoTotal" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
                currency_data["MontoGravadoTotalOtraMoneda"] = round(
                    float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoGravadoTotal"])
                    / rate,
                    2,
                )

            if "MontoGravadoI1" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
                currency_data["MontoGravado1OtraMoneda"] = round(
                    float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoGravadoI1"])
                    / rate,
                    2,
                )

            if "MontoGravadoI2" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
                currency_data["MontoGravado2OtraMoneda"] = round(
                    float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoGravadoI2"])
                    / rate,
                    2,
                )

            if "MontoGravadoI3" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
                currency_data["MontoGravado3OtraMoneda"] = round(
                    float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoGravadoI3"])
                    / rate,
                    2,
                )

        if "MontoExento" in ecf_object_data["ECF"]["Encabezado"]["Totales"] and l10n_do_ncf_type not in ("46"):
            currency_data["MontoExentoOtraMoneda"] = round(
                float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoExento"]) / rate, 2
            )

        if "MontoGravadoTotal" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
            currency_data["TotalITBISOtraMoneda"] = round(
                float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["TotalITBIS"]) / rate,
                2,
            )
        if "MontoGravadoI1" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
            currency_data["TotalITBIS1OtraMoneda"] = round(
                float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["TotalITBIS1"]) / rate,
                2,
            )
        if "MontoGravadoI2" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
            currency_data["TotalITBIS2OtraMoneda"] = round(
                float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["TotalITBIS2"]) / rate,
                2,
            )
        if "MontoGravadoI3" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
            currency_data["TotalITBIS3OtraMoneda"] = round(
                float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["TotalITBIS3"]) / rate,
                2,
            )

        currency_data["MontoTotalOtraMoneda"] = round(self.amount_total, 2)

        return currency_data

    def _get_item_withholding_vals(self, invoice_line):
        """ Returns invoice line withholding taxes values """

        l10n_do_ncf_type = self.get_l10n_do_ncf_type()

        line_withholding_vals = invoice_line.tax_ids.compute_all(
            price_unit=invoice_line.price_unit * (1 - (invoice_line.discount / 100.0)),
            currency=invoice_line.currency_id,
            quantity=invoice_line.quantity,
            product=invoice_line.product_id,
            partner=invoice_line.move_id.partner_id,
            is_refund=True if invoice_line.move_id.move_type == "in_refund" else False,
        )

        withholding_vals = od()

        if hasattr(invoice_line, 'monto_itbis_retenido'):

            if invoice_line.monto_itbis_retenido != 0:
                itbis_withhold_amount = abs(invoice_line.monto_itbis_retenido)

            else:
                itbis_withhold_amount = abs(
                    sum(
                        tax["amount"]
                        for tax in line_withholding_vals["taxes"]
                        if tax["amount"] < 0
                        and 'ITBIS' in str(self.env["account.tax"].browse(tax["id"]).tax_group_id.name)
                    )
                )

        else:

            itbis_withhold_amount = abs(
                sum(
                    tax["amount"]
                    for tax in line_withholding_vals["taxes"]
                    if tax["amount"] < 0
                    and 'ITBIS' in str(self.env["account.tax"].browse(tax["id"]).tax_group_id.name)
                )
            )

        if hasattr(invoice_line, 'monto_isr_retenido'):

            if invoice_line.monto_isr_retenido != 0:
                isr_withhold_amount = abs(invoice_line.monto_isr_retenido)
            else:
                isr_withhold_amount = abs(
                    sum(
                        tax["amount"]
                        for tax in line_withholding_vals["taxes"]
                        if tax["amount"] < 0
                        and 'ISR' in str(self.env["account.tax"].browse(tax["id"]).tax_group_id.name)
                    )
                )

        else:
            isr_withhold_amount = abs(
                sum(
                    tax["amount"]
                    for tax in line_withholding_vals["taxes"]
                    if tax["amount"] < 0
                    and 'ISR' in str(self.env["account.tax"].browse(tax["id"]).tax_group_id.name)
                )
            )

        if l10n_do_ncf_type != '47':
            if self.withholded_itbis > 0 and not itbis_withhold_amount:
                withholding_vals["MontoITBISRetenido"] = "{:.2f}".format(abs(
                    round(self.withholded_itbis / len(self.invoice_line_ids.filtered(lambda x: (x.quantity * x.price_unit) > 0)), 2)
                ))
            else:
                withholding_vals["MontoITBISRetenido"] = "{:.2f}".format(abs(
                    round(itbis_withhold_amount, 2)
                ))


        if self.income_withholding > 0 and not isr_withhold_amount:
            withholding_vals["MontoISRRetenido"] = "{:.2f}".format(abs(
                    round(self.income_withholding / len(self.invoice_line_ids.filtered(lambda x: (x.quantity * x.price_unit) > 0)), 2)
                ))
        else:
            withholding_vals["MontoISRRetenido"] = "{:.2f}".format(abs(
                    round(isr_withhold_amount, 2)
                ))




        return withholding_vals

    def _get_Item_list(self, ecf_object_data):
        """Product lines related values"""
        self.ensure_one()

        itbis_group = self.env.ref("l10n_do.group_itbis")
        is_company_currency = self.is_company_currency()
        l10n_do_ncf_type = self.get_l10n_do_ncf_type()

        def get_invoicing_indicator(inv_line):
            "IndicadorFacturacion"
            if not inv_line.tax_ids:
                return 4
            tax_set = set(
                tax.amount
                for tax in inv_line.tax_ids
                if tax.tax_group_id.id == itbis_group.id
            )

            exento = set('Exento' in tax.name for tax in inv_line.tax_ids)

            
            if len(tax_set) > 1 or 18 in tax_set:
                return 1
            elif 16 in tax_set:
                return 2
            elif l10n_do_ncf_type in ("46") and 0 in tax_set:
                return 3
            else:
                return 4

        lines_data = []

        for i, line in enumerate(
            self.invoice_line_ids.filtered(lambda l: not l.display_type).sorted(
                "sequence"
            ),
            1,
        ):

            rate = 1
            if "OtraMoneda" in ecf_object_data["ECF"]["Encabezado"]:
                rate = ecf_object_data["ECF"]["Encabezado"]["OtraMoneda"]["TipoCambio"]

            line_dict = od()
            product = line.product_id
            if product:
                product_name = product.name if len(product.name) > 0 else line.name
            else:
                product_name = line.name
            product_description = (product.ecf_descripcion_item if product.ecf_descripcion_item else False) if product else False
            line_dict["NumeroLinea"] = i
            line_dict["IndicadorFacturacion"] = get_invoicing_indicator(line)

            if l10n_do_ncf_type in ("41", "47"):
                withholding_vals = od([("IndicadorAgenteRetencionoPercepcion", 1)])
                for k, v in self._get_item_withholding_vals(line).items():
                    withholding_vals[k] = "{:.2f}".format(abs(
                    round(round(
                        float(v) if is_company_currency else float(v) * rate, 2
                    ), 2)
                ))
                line_dict["Retencion"] = withholding_vals

            # line_dict["NombreItem"] = product.name if product else line.name
            line_dict["NombreItem"] = (
                (product_name[:78] + "..") if len(product_name) > 78 else product_name
            )
            line_dict["IndicadorBienoServicio"] = (
                "2"
                if (product and product.type == "service") or l10n_do_ncf_type == "47"
                else "1"
            )

            if product_description:
                line_dict["DescripcionItem"] = product_description


            line_dict["CantidadItem"] = "{:.2f}".format(line.quantity)

            if line.product_id.ecf_unidad_medida:
                line_dict["UnidadMedida"] = line.product_id.ecf_unidad_medida

            if line.product_id:
                if line.product_id.ecf_cantidad_referencia:
                    line_dict["CantidadReferencia"] = line.product_id.ecf_cantidad_referencia
                if line.product_id.ecf_unidad_referencia:
                    line_dict["UnidadReferencia"] = line.product_id.ecf_unidad_referencia

                if line.product_id.ecf_sub_cantidad:
                    line_dict["TablaSubcantidad"] = {}
                    line_dict["TablaSubcantidad"]["SubcantidadItem"] = {}
                    line_dict["TablaSubcantidad"]["SubcantidadItem"]["Subcantidad"] = line.product_id.ecf_sub_cantidad
                    line_dict["TablaSubcantidad"]["SubcantidadItem"]["CodigoSubcantidad"] = line.product_id.ecf_cantidad_referencia

                if line.product_id.ecf_grados_alcohol:
                    line_dict["GradosAlcohol"] = line.product_id.ecf_grados_alcohol

                if line.product_id.ecf_precio_unitario_referencia:
                    line_dict["PrecioUnitarioReferencia"] = line.product_id.ecf_precio_unitario_referencia

            precio_unitario = abs(
                line.price_unit
                if is_company_currency
                else round(line.price_unit * rate, 4)
            )

            decimals = str(precio_unitario)[::-1].find('.')

            division = 1

            for tax in line.tax_ids:
                if tax.price_include and tax.amount_type == 'percent':
                    division = (tax.amount/100) + 1

            itbis_data = {
                "total_taxed_amount": 0,
                "18_taxed_base": 0,
                "18_taxed_amount": 0,
                "16_taxed_base": 0,
                "16_taxed_amount": 0,
                "0_taxed_base": 0,
                "0_taxed_amount": 0,
                "exempt_amount": 0,
                "itbis_withholding_amount": 0,
                "isr_withholding_amount": 0,
            }

            tax_data = [
                line.tax_ids.compute_all(
                    price_unit=line.price_unit * (1 - (line.discount / 100.0)),
                    currency=line.currency_id,
                    product=line.product_id,
                    partner=line.move_id.partner_id,
                    quantity=line.quantity
                )
            ]

            itbis_data["total_taxed_amount"] = sum(
                line["total_excluded"] for line in tax_data
            )

            is_tax_included = bool(
                    any(
                        True
                        for t in self.invoice_line_ids.tax_ids.filtered(
                            lambda tax: tax.tax_group_id.id == itbis_group.id
                        )
                        if t.price_include
                    )
                )

            is_tax_included_line = False
            impuestos_adicionales = 0.0

            for line_taxes in tax_data:
                for tax in line_taxes["taxes"]:
                    if not tax["amount"] and not l10n_do_ncf_type in ("46"):
                        itbis_data["exempt_amount"] += tax["base"]

                    tax_id = self.env["account.tax"].browse(tax["id"])

                    if tax_id.ecf_tipo_impuesto:
                        impuestos_adicionales += tax["amount"]



                    is_tax_included_line = tax_id.price_include

                    if tax_id.amount == 18:
                        itbis_data["18_taxed_base"] += tax["base"]
                        itbis_data["18_taxed_amount"] += tax["amount"]
                    elif tax_id.amount == 16:
                        itbis_data["16_taxed_base"] += tax["base"]
                        itbis_data["16_taxed_amount"] += tax["amount"]
                    elif tax_id.amount == 0 and l10n_do_ncf_type in ("46","41"):
                        itbis_data["0_taxed_base"] += tax["base"]
                        itbis_data["0_taxed_amount"] += tax["amount"]
                    elif tax_id.amount < 0 and tax_id.tax_group_id == self.env.ref(
                            "l10n_do.group_itbis"
                    ):
                        itbis_data["itbis_withholding_amount"] += tax["amount"]
                    elif tax_id.amount < 0 and tax_id.tax_group_id == self.env.ref(
                            "l10n_do.group_isr"
                    ):
                        itbis_data["isr_withholding_amount"] += tax["amount"]
            if self.withholded_itbis > 0:
                itbis_data["itbis_withholding_amount"] += self.withholded_itbis

            if self.income_withholding > 0:
                itbis_data["isr_withholding_amount"] += self.income_withholding

            # raise UserError(_("%s", itbis_data))


            if is_tax_included:
                total_item = itbis_data['18_taxed_base'] + itbis_data['18_taxed_amount'] + itbis_data['16_taxed_base'] + \
                         itbis_data['16_taxed_amount'] + itbis_data['0_taxed_base']
            else:
                total_item = itbis_data['18_taxed_base'] + itbis_data['16_taxed_base'] + itbis_data['0_taxed_base']

            if total_item == 0.0:
                total_item = line.price_subtotal



            if is_tax_included_line:
                total_item_currency = itbis_data['18_taxed_base'] + itbis_data['18_taxed_amount'] + itbis_data['16_taxed_base'] + \
                             itbis_data['16_taxed_amount'] + itbis_data['0_taxed_base']
            else:
                total_item_currency = itbis_data['18_taxed_base'] + itbis_data['16_taxed_base'] + itbis_data['0_taxed_base']

            if total_item_currency == 0.0:
                total_item_currency = line.price_subtotal

            price_wo_discount = line.quantity * line.price_unit
            price_with_discount = price_wo_discount * (1 - (line.discount / 100.0))

            discount_amount = (
                abs(round(price_with_discount - price_wo_discount, 2))
                if line.discount
                else 0
            )

            currency_discount_amount = discount_amount
            discount_amount = (
                discount_amount
                if is_company_currency
                else round(discount_amount * rate, 2)
            )

            monto_item = abs(
                round(
                    total_item
                    if is_company_currency
                    else total_item * rate,
                    2,
                ) + discount_amount
            )

            decimals2 = str(monto_item / line.quantity)[::-1].find('.')
            decimales_a_redondear = 2

            if decimals2 <= 2:
                line_dict["PrecioUnitarioItem"] = "{:.2f}".format(round(monto_item / line.quantity, 2))
                decimales_a_redondear = 2
            elif decimals2 == 3:
                line_dict["PrecioUnitarioItem"] = "{:.3f}".format(round(monto_item / line.quantity, 3))
                decimales_a_redondear = 3
            elif decimals2 >= 4:
                line_dict["PrecioUnitarioItem"] = "{:.4f}".format(round(monto_item / line.quantity, 4))
                decimales_a_redondear = 4





            if line.discount:
                line_dict["DescuentoMonto"] = discount_amount
                line_dict["TablaSubDescuento"] = {
                    "SubDescuento":
                        {
                            "TipoSubDescuento": "$",
                            # "SubDescuentoPorcentaje": line.discount,
                            "MontoSubDescuento": "{:.2f}".format(round(discount_amount)),
                        },

                }

            for tax in line.tax_ids.filtered(lambda x: x.ecf_tipo_impuesto):
                if not "TablaImpuestoAdicional" in line_dict:
                    line_dict["TablaImpuestoAdicional"] = {}
                    line_dict["TablaImpuestoAdicional"] = [{"ImpuestoAdicional":{"TipoImpuesto": tax.ecf_tipo_impuesto}}]
                else:
                    line_dict["TablaImpuestoAdicional"].append({"ImpuestoAdicional":{"TipoImpuesto": tax.ecf_tipo_impuesto}})

            if not is_company_currency:
                line_dict["OtraMonedaDetalle"] = {
                    "PrecioOtraMoneda": abs(round(line.price_unit, decimales_a_redondear)),
                    "DescuentoOtraMoneda": currency_discount_amount,
                    "MontoItemOtraMoneda": abs(round(total_item_currency, 2)),
                }



            line_dict["MontoItem"] = "{:.2f}".format(monto_item - discount_amount)



            lines_data.append(line_dict)



        # raise UserError(_("%s", lines_data))

        return lines_data

    def _get_InformacionReferencia_data(self, ecf_object_data):
        """Data included Debit/Credit Note"""
        self.ensure_one()
        reference_info_data = od({})

        origin_id = (
            self.search([("ref", "=", self.l10n_do_origin_ncf)], limit=1)
            if self.get_l10n_do_ncf_type() in ("34","33")
            else self.debit_origin_id
        )

        if not origin_id:
            raise ValidationError(_("Could not found origin document."))

        if "InformacionReferencia" not in ecf_object_data["ECF"]:
            ecf_object_data["ECF"]["InformacionReferencia"] = od({})
        reference_info_data["NCFModificado"] = origin_id.ref
        reference_info_data["FechaNCFModificado"] = dt.strftime(
            origin_id.invoice_date, "%d-%m-%Y"
        )
        reference_info_data["CodigoModificacion"] = self.l10n_do_ecf_modification_code

        return reference_info_data

    def _get_IA_data(self):
        """Data included Debit/Credit Note"""
        self.ensure_one()
        IA_data = od({})

        if self.ecf_numero_de_contenedor:
            IA_data["NumeroContenedor"] = self.ecf_numero_de_contenedor

        if self.ecf_numero_de_referencia:
            IA_data["NumeroReferencia"] = self.ecf_numero_de_referencia

        return IA_data



    def _get_invoice_data_object(self,total_pesos):
        """Builds invoice e-CF for final consumers data object to be send to DGII

        Invoice e-CF data object is composed by the following main parts:

        * Encabezado -- Corresponds to the identification of the e-CF, where it contains
        the issuer, buyer and tax data
        * Detalle de Bienes o Servicios -- In this section one line must be detailed for
        each item
        * Subtotales Informativos -- These subtotals do not increase or decrease the tax
        base, nor do they modify the totalizing fields; they are only informative fields
        * Descuentos o Recargos -- This section is used to specify global discounts or
        surcharges that affect the total e-CF. Item-by-item specification is not
        required
        * Paginación -- This section indicates the number of e-CF pages in the Printed
        Representation and what items will be on each one. This should be repeated for
        the total number of pages specified
        * Información de Referencia -- This section must detail the e-CFs modified by
        Electronic Credit or Debit Note and the eCFs issued due to the replacement of
        a voucher issued in contingency.
        * Fecha y Hora de la firma digital -- Date and Time of the digital signature
        * Firma Digital -- Digital Signature on all the above information to guarantee
        the integrity of the e-CF

        Data order is a key aspect of e-CF issuing. For the sake of this matter,
        OrderedDict objects are used to compose the whole e-CF.

        Eg:

        OrderedDict([('ECF',
        OrderedDict([('Encabezado',
        OrderedDict([('Version', '1.0'),
        ('IdDoc',
        OrderedDict([('TipoeCF', '31'),
                     ('eNCF', 'E310000000007'),
                     ('FechaVencimientoSecuencia', '31-12-2020'),
                     ('IndicadorMontoGravado', 0),
                     ('TipoIngresos', '01'),
                     ('TipoPago', 2),
                     ('FechaLimitePago', '20-06-2020'),
                     ('TerminoPago', '0 días')])),
        ('Emisor',
        OrderedDict([('RNCEmisor', '131793916'),
                     ('RazonSocialEmisor', 'INDEXA SRL'),
                     ('NombreComercial', ''),
                     ('Sucursal', ''),
                     ('DireccionEmisor', 'Calle Rafael Augusto Sánchez 86'),
                     ('FechaEmision', '20-06-2020')])),
        ('Comprador',
        OrderedDict([('RNCComprador', '101654325'),
                     ('RazonSocialComprador', 'CONSORCIO DE TARJETAS DOMINICANAS S A')])),
        ('Totales',
        OrderedDict([('MontoGravadoTotal', 4520.0),
                     ('MontoGravadoI1', 4520.0),
                     ('ITBIS1', '18'),
                     ('TotalITBIS', 813.6),
                     ('TotalITBIS1', 813.6),
                     ('MontoTotal', 10667.2)]))])),
        ('DetallesItems',
        OrderedDict([('Item',
        [OrderedDict([('NumeroLinea', 1),
                    ('IndicadorFacturacion', 1),
                    ('NombreItem', 'Product A'),
                    ('IndicadorBienoServicio', '1'),
                    ('DescripcionItem', 'Product A'),
                    ('CantidadItem', 5.0),
                    ('PrecioUnitarioItem', 800.0),
                    ('MontoItem', 4000.0)])])])),
        ('FechaHoraFirma', '20-06-2020 23:51:44'),
        ('_ANY_', '')]))])

        """
        self.ensure_one()

        l10n_do_ncf_type = self.get_l10n_do_ncf_type()
        is_company_currency = self.is_company_currency()

        # At this point, ecf_object_data only contains required
        # fields in all e-CF's types
        monto_total_ecf, totales = self._get_Totales_data(total_pesos)
        fecha_hora_firma = fields.Datetime.context_timestamp(
                                self.with_context(tz="America/Santo_Domingo"),
                                fields.Datetime.now(),
                            )
        if not self.l10n_do_ecf_sign_date:
            self.l10n_do_ecf_sign_date = fecha_hora_firma.strftime("%Y-%m-%d %H:%M:%S")
        if l10n_do_ncf_type == '32' and total_pesos < 250000:
            ecf_object_data = od(
                {
                    "RFCE": od(
                        {
                            "Encabezado": od(
                                {
                                    "Version": "1.0",  # is this value going to change anytime?
                                    "IdDoc": self._get_IdDoc_data(total_pesos),
                                    "Emisor": self._get_Emisor_data(total_pesos),
                                    "Comprador": self._get_Comprador_data(total_pesos),
                                    "InformacionesAdicionales": self._get_IA_data(),
                                    "Totales": totales,
                                }
                            ),
                        }
                    ),
                }
            )

        else:
            if not self.l10n_do_ecf_sign_date:
                self.l10n_do_ecf_sign_date = fecha_hora_firma.strftime("%Y-%m-%d %H:%M:%S")
            ecf_object_data = od(
                {
                    "ECF": od(
                        {
                            "Encabezado": od(
                                {
                                    "Version": "1.0",  # is this value going to change anytime?
                                    "IdDoc": self._get_IdDoc_data(total_pesos),
                                    "Emisor": self._get_Emisor_data(total_pesos),
                                    "Comprador": self._get_Comprador_data(total_pesos),
                                    "InformacionesAdicionales": self._get_IA_data(),
                                    "Totales": totales,
                                }
                            ),
                            "DetallesItems": od({}),
                            "InformacionReferencia": od({}),
                            # This is a dummy date. The one we use in the digital stamp
                            # is the one received from the external service
                            "FechaHoraFirma": fecha_hora_firma.strftime("%d-%m-%Y %H:%M:%S"),
                        }
                    ),
                }
            )



        if l10n_do_ncf_type in ("43","47"):
            del ecf_object_data["ECF"]["Encabezado"]["Comprador"]

        if not is_company_currency:
            if l10n_do_ncf_type == '32' and total_pesos < 250000:
                bool = True
            else:
                if "OtraMoneda" not in ecf_object_data["ECF"]["Encabezado"]:
                    ecf_object_data["ECF"]["Encabezado"]["OtraMoneda"] = od({})
                ecf_object_data["ECF"]["Encabezado"][
                    "OtraMoneda"
                ] = self._get_OtraMoneda_data(ecf_object_data)

        # Invoice lines
        if l10n_do_ncf_type == '32' and total_pesos < 250000:
            if not self.ecf_numero_de_contenedor and not self.ecf_numero_de_referencia and "InformacionesAdicionales" in \
                    ecf_object_data["RFCE"]["Encabezado"]:
                del ecf_object_data["RFCE"]["Encabezado"]["InformacionesAdicionales"]
            d = hashlib.md5(str(random.randint(100000,999999)).encode('utf-8')).digest();
            d = base64.b64encode(d);
            """ ecf_object_data["RFCE"]["Encabezado"]["CodigoSeguridadeCF"] = d.decode('utf-8')[0:6] """
        else:
            if not self.ecf_numero_de_contenedor and not self.ecf_numero_de_referencia and "InformacionesAdicionales" in \
                    ecf_object_data["ECF"]["Encabezado"]:
                del ecf_object_data["ECF"]["Encabezado"]["InformacionesAdicionales"]
            ecf_object_data["ECF"]["DetallesItems"] = self._get_Item_list(
                ecf_object_data
            )

            # Seccion para corregir diferencias en precio unitario vs montogravado 1 y 2. Se presenta en escenarios cuando
            # el monto de la factura es forzado a 1 tasa en vez de calculado.

            monto_total_lineas_18 = 0.0
            monto_total_lineas_16 = 0.0
            for l in ecf_object_data["ECF"]["DetallesItems"]:
                if 'MontoItem' in l and 'IndicadorFacturacion' in l:
                    if l['IndicadorFacturacion'] == 1:
                        monto_total_lineas_18 += float(l['MontoItem'])
                    if l['IndicadorFacturacion'] == 2:
                        monto_total_lineas_16 += float(l['MontoItem'])

            total_a_sumar = 0.0
            if "MontoGravadoI1" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
                if float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoGravadoI1"]) != monto_total_lineas_18:
                    diferencia = float(
                        ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoGravadoI1"]) - monto_total_lineas_18
                    for l in ecf_object_data["ECF"]["DetallesItems"]:
                        if 'MontoItem' in l and 'IndicadorFacturacion' in l:
                            if l['IndicadorFacturacion'] == 1 and abs(diferencia) < float(l['MontoItem']):
                                monto_original = float(l['MontoItem'])
                                descuento = float(l['DescuentoMonto']) if 'DescuentoMonto' in l else 0.0
                                monto_cambiado = round(monto_original + diferencia, 2)
                                l['MontoItem'] = monto_cambiado

                                cantidad_item = float(l['CantidadItem'])
                                l['PrecioUnitarioItem'] = str(
                                    round(monto_cambiado / cantidad_item, 4)) if cantidad_item > 0 else l[
                                    'PrecioUnitarioItem']
                                break

            if "MontoGravadoI2" in ecf_object_data["ECF"]["Encabezado"]["Totales"]:
                if float(ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoGravadoI2"]) != monto_total_lineas_16:
                    diferencia = float(
                        ecf_object_data["ECF"]["Encabezado"]["Totales"]["MontoGravadoI2"]) - monto_total_lineas_16
                    for l in ecf_object_data["ECF"]["DetallesItems"]:
                        if 'MontoItem' in l and 'IndicadorFacturacion' in l:
                            if l['IndicadorFacturacion'] == 1 and abs(diferencia) > float(l['MontoItem']):
                                monto_original = float(l['MontoItem'])
                                descuento = float(l['DescuentoMonto']) if 'DescuentoMonto' in l else 0.0
                                monto_cambiado = round(monto_original + diferencia, 2)
                                l['MontoItem'] = monto_cambiado

                                cantidad_item = float(l['CantidadItem'])
                                l['PrecioUnitarioItem'] = str(
                                    round(monto_cambiado / cantidad_item, 4)) if cantidad_item > 0 else l[
                                    'PrecioUnitarioItem']
                                break




        if l10n_do_ncf_type in ("33", "34"):
            ecf_object_data["ECF"][
                "InformacionReferencia"
            ] = self._get_InformacionReferencia_data(ecf_object_data)
        else:
            if "ECF" in ecf_object_data:
                del ecf_object_data["ECF"]["InformacionReferencia"]

        if l10n_do_ncf_type == '32' and total_pesos < 250000:
            self.monto_total_ecf = monto_total_ecf
        else:
            self.monto_total_ecf = monto_total_ecf

            if self.partner_id.bank_ids.filtered(lambda x: x.payment_method_ecf != False) and l10n_do_ncf_type not in ('33','34') and l10n_do_ncf_type[0:1] != '4':
                for rec in self.partner_id.bank_ids:
                    ecf_object_data["ECF"]["Encabezado"]["IdDoc"]["TablaFormasPago"] = {}
                    ecf_object_data["ECF"]["Encabezado"]["IdDoc"]["TablaFormasPago"]["FormaDePago"] = {}
                    ecf_object_data["ECF"]["Encabezado"]["IdDoc"]["TablaFormasPago"]["FormaDePago"]["FormaPago"] = rec.payment_method_ecf
                    ecf_object_data["ECF"]["Encabezado"]["IdDoc"]["TablaFormasPago"]["FormaDePago"]["MontoPago"] = "{:.2f}".format(round(rec.monto_distribucion_ecf * monto_total_ecf,2))


        return ecf_object_data

    def log_error_message(self, body):
        self.ensure_one()

        msg_body = "<ul>"
        try:
            error_message = json.loads(body)
            for msg in list(error_message.get("mensajes") or []):
                msg_body += "<li>%s</li>" % msg.get("valor")
        except SyntaxError:
            msg_body += "<li>%s</li>" % body

        msg_body += "</ul>"
        dgii_action = (
            _("rejected")
            if self.l10n_do_ecf_send_state == "delivered_refused"
            else _("Conditionally Accepted")
        )
        refused_msg = _("DGII has %s this ECF. Details:\n") % dgii_action

        refused_msg += msg_body

        # Use sudo to post message because we want user actions
        # separated of ECF messages posts
        self.sudo().message_post(body=refused_msg)

    def _show_service_unreachable_message(self):
        msg = _(
            "ECF %s can not be sent due External Service communication issue. "
            "Try again in while or enable company contingency status" % self.ref
        )
        raise ValidationError(msg)

    def calculate_xml(self):

        for invoice in self:

            cert = invoice.company_id.archivo_cer
            password = invoice.company_id.contrasena or ''

            if not cert:
                raise UserError(_("No puede generar XML firmados para esta compania, pues el certificado .pfx no esta"
                                  "adjunto. Compania: %s", invoice.company_id.name))



            invoice_vals = {}

            signature_fc = ''

            req = requests.Session()
            url = "http://localhost:5000/api/DgiiSigner"

            headers = {
                'Content-Type': 'application/json'
            }
            

            if not invoice.l10n_do_ecf_edi_file:

                ecf_data = invoice._get_invoice_data_object(self.amount_total_signed)


                if 'RFCE' in ecf_data:

                    if not invoice.l10n_do_ecf_edi_file_fc:
                        ecf_data_fc = invoice._get_invoice_data_object(251000)

                        ecf_xml_fc = dicttoxml(json.loads(json.dumps(ecf_data_fc)),root=False, attr_type=False)

                        xml_file_fc = ecf_xml_fc.decode('utf-8').replace('"', "'").replace('item','Item').replace("<Item><ImpuestoAdicional>","<ImpuestoAdicional>").\
                        replace("</ImpuestoAdicional></Item>","</ImpuestoAdicional>").replace("<Item><ImpuestoAdicional>","<ImpuestoAdicional>").\
                        replace("</ImpuestoAdicional></Item>","</ImpuestoAdicional>")

                        # raise UserError(_("%s", xml_file))

                        data_fc = {"xml": xml_file_fc, "cert": cert.decode('utf-8'),
                                "pass": password}

                        response_fc = req.post(url, headers=headers, data=json.dumps(data_fc))

                        result_json_fc = json.loads(response_fc.text)

                        ecf_data['RFCE']['Encabezado']['CodigoSeguridadeCF'] = result_json_fc['signature'][0:6]

                        if hasattr(invoice,'l10n_do_ecf_edi_file_fc'):
                            invoice.write(
                                {
                                    "l10n_do_ecf_edi_file_name_fc": "%s%s.xml" % (invoice.company_id.vat,invoice.ref),
                                    "l10n_do_ecf_edi_file_fc": base64.b64encode(result_json_fc['xml'].encode('utf-8')),
                                }
                            )


                ecf_xml = dicttoxml(json.loads(json.dumps(ecf_data)),root=False, attr_type=False)


            # raise UserError(_("%s",ecf_xml.decode('utf-8')))
                xml_file = ecf_xml.decode('utf-8').replace('"', "'").replace('item','Item').replace("<Item><ImpuestoAdicional>","<ImpuestoAdicional>").\
                replace("</ImpuestoAdicional></Item>","</ImpuestoAdicional>").replace("<Item><ImpuestoAdicional>","<ImpuestoAdicional>").\
                replace("</ImpuestoAdicional></Item>","</ImpuestoAdicional>")

                xml_file_string = ET.fromstring(xml_file)

                xml_file = ET.tostring(xml_file_string, pretty_print=True)

                # raise UserError(_("%s", xml_file))


                # raise UserError(_("%s", result_json['signature']))

                # datetime.strptime(result_json['date'], '%d-%m-%Y %H:%M:%S')
                if not invoice.l10n_do_ecf_edi_file:
                    invoice_vals.update(
                        {

                            "l10n_do_ecf_edi_file_name": "%s%s.xml" % (invoice.company_id.vat,invoice.ref),
                            "l10n_do_ecf_edi_file": base64.b64encode(xml_file),
                        }
                    )

            invoice.write(invoice_vals)
        return True

    def calculate_ecf_data(self):

        for invoice in self:

            cert = invoice.company_id.archivo_cer
            password = invoice.company_id.contrasena or ''

            if not cert:
                raise UserError(_("No puede generar XML firmados para esta compania, pues el certificado .pfx no esta"
                                  "adjunto. Compania: %s", invoice.company_id.name))



            invoice_vals = {}

            signature_fc = ''

            req = requests.Session()
            url = "http://localhost:5000/api/DgiiSigner"

            headers = {
                'Content-Type': 'application/json'
            }

            if not invoice.l10n_do_ecf_edi_file:

                ecf_data = invoice._get_invoice_data_object(self.amount_total_signed)


                if 'RFCE' in ecf_data:

                    if not invoice.l10n_do_ecf_edi_file_fc:
                        ecf_data_fc = invoice._get_invoice_data_object(251000)

                        ecf_xml_fc = dicttoxml(json.loads(json.dumps(ecf_data_fc)),root=False, attr_type=False)

                        xml_file_fc = ecf_xml_fc.decode('utf-8').replace('"', "'").replace('item','Item').replace("<Item><ImpuestoAdicional>","<ImpuestoAdicional>").\
                        replace("</ImpuestoAdicional></Item>","</ImpuestoAdicional>").replace("<Item><ImpuestoAdicional>","<ImpuestoAdicional>").\
                        replace("</ImpuestoAdicional></Item>","</ImpuestoAdicional>")

                        # raise UserError(_("%s", xml_file))

                        data_fc = {"xml": xml_file_fc, "cert": cert.decode('utf-8'),
                                "pass": password}

                        response_fc = req.post(url, headers=headers, data=json.dumps(data_fc))

                        result_json_fc = json.loads(response_fc.text)

                        ecf_data['RFCE']['Encabezado']['CodigoSeguridadeCF'] = result_json_fc['signature'][0:6]

                        signature_fc = result_json_fc['signature'][0:6]

                        if hasattr(invoice,'l10n_do_ecf_edi_file_fc'):

                            invoice.write(
                                {
                                    "l10n_do_ecf_edi_file_name_fc": "%s%s.xml" % (invoice.company_id.vat,invoice.ref),
                                    "l10n_do_ecf_edi_file_fc": base64.b64encode(result_json_fc['xml'].encode('utf-8')),
                                }
                            )
                    else:
                        ecf_xml_fc = base64.b64decode(invoice.l10n_do_ecf_edi_file_fc)
                        ecf_xml_fc_string = ET.fromstring(ecf_xml_fc.decode('utf-8'))


                        ecf_data['RFCE']['Encabezado']['CodigoSeguridadeCF'] = ecf_xml_fc_string.find(".//CodigoSeguridadeCF").text

                        signature_fc = ecf_xml_fc_string.find(".//CodigoSeguridadeCF").text




                ecf_xml = dicttoxml(json.loads(json.dumps(ecf_data)),root=False, attr_type=False)
            else:
                ecf_xml = base64.b64decode(invoice.l10n_do_ecf_edi_file)


                ecf_xml_string = ET.fromstring(ecf_xml.decode('utf-8'))

                sig = ecf_xml_string.find(".//FechaHoraFirma")

                rnc = ecf_xml_string.find(".//RNCEmisor")

                ncf = ecf_xml_string.find(".//eNCF")

                invoice.ref = ncf.text

                fecha_hora_firma = fields.Datetime.context_timestamp(
                                self.with_context(tz="America/Santo_Domingo"),
                                fields.Datetime.now(),
                            )
                sig.text = fecha_hora_firma.strftime("%d-%m-%Y %H:%M:%S")
                rnc.text = invoice.company_id.partner_id.vat
                if not invoice.l10n_do_ecf_sign_date:
                    invoice.l10n_do_ecf_sign_date = fecha_hora_firma.strftime("%Y-%m-%d %H:%M:%S")

                ecf_xml = ET.tostring(ecf_xml_string)

            
            

            # raise UserError(_("%s",ecf_xml.decode('utf-8')))
            xml_file = ecf_xml.decode('utf-8').replace('"', "'").replace('item','Item').replace("<Item><ImpuestoAdicional>","<ImpuestoAdicional>").\
            replace("</ImpuestoAdicional></Item>","</ImpuestoAdicional>").replace("<Item><ImpuestoAdicional>","<ImpuestoAdicional>").\
            replace("</ImpuestoAdicional></Item>","</ImpuestoAdicional>")

            # raise UserError(_("%s", xml_file))

            data = {"xml": xml_file, "cert": cert.decode('utf-8'),
                    "pass": password}

            response = req.post(url, headers=headers, data=json.dumps(data))

            result_json = json.loads(response.text)

            xml_file_string = ET.fromstring(result_json['xml'])

            


            xml_file_string_out = ET.tostring(xml_file_string)

            # raise UserError(_("%s", result_json['signature']))

            # datetime.strptime(result_json['date'], '%d-%m-%Y %H:%M:%S')
            if not invoice.l10n_do_ecf_edi_file:
                invoice_vals.update(
                    {

                        "l10n_do_ecf_edi_file_name": "%s%s.xml" % (invoice.company_id.vat,invoice.ref),
                        "l10n_do_ecf_edi_file": base64.b64encode(xml_file_string_out),
                        "l10n_do_ecf_security_code":result_json['signature'][0:6] if signature_fc == '' else signature_fc,
                    }
                )
            else:
                invoice_vals.update(
                    {

                        "l10n_do_ecf_edi_file_name": "%s%s.xml" % (invoice.company_id.vat,invoice.ref),
                        "l10n_do_ecf_edi_file": base64.b64encode(xml_file_string_out),
                        "l10n_do_ecf_security_code": result_json['signature'][
                                                     0:6] if signature_fc == '' else signature_fc,
                    }
                )

            invoice.write(invoice_vals)
        return True

    def _send_ecf_submit_request(self, ecf_data, ecf_name):
        self.ensure_one()
        req = requests.Session()

        payload = {}
        files = [
            ('xml',
             (ecf_name, ecf_data, 'text/xml'))
        ]

        if self.company_id.token_expire <= datetime.now():
            self.company_id.post_semilla_dgii()

        headers = { 'Authorization': 'Bearer ' + self.company_id.token,}

        url = "https://ecf.dgii.gov.do/%s/Recepcion/api/FacturasElectronicas" % \
              (self.company_id.l10n_do_ecf_service_env)

        return req.post(url, headers=headers, data=payload, files=files)

    def _send_efc_submit_request(self, ecf_data, ecf_name):
        self.ensure_one()
        req = requests.Session()

        payload = {}
        files = [
            ('xml',
             (ecf_name, ecf_data, 'text/xml'))
        ]

        if self.company_id.token_expire <= datetime.now():
            self.company_id.post_semilla_dgii()

        headers = { 'Authorization': 'Bearer ' + self.company_id.token,}

        url = "https://fc.dgii.gov.do/%s/RecepcionFC/api/recepcion/ecf" % \
              (self.company_id.l10n_do_ecf_service_env)

        return req.post(url, headers=headers, data=payload, files=files)

    def _send_ecf_status_request(self, trackid,invoice):

        req = requests.Session()

        if self.company_id.token_expire <= datetime.now():
            self.company_id.post_semilla_dgii()

        headers = { 'Authorization': 'Bearer ' + invoice.company_id.token,}

        url = "https://ecf.dgii.gov.do/%s/ConsultaResultado/api/Consultas/Estado?TrackId=%s" % \
              (invoice.company_id.l10n_do_ecf_service_env,trackid)
        response = req.get(url, headers=headers)
        return response

    def send_ecf_data(self):

        for invoice in self:

            if invoice.l10n_do_ecf_send_state in (
                "delivered_accepted",
                "conditionally_accepted",
            ):
                raise ValidationError(_("Resend a Delivered e-CF is not allowed."))

            ecf_data = base64.b64decode(invoice.l10n_do_ecf_edi_file)

            l10n_do_ncf_type = invoice.get_l10n_do_ncf_type()

            # raise UserError(_("%s", ecf_data))

            invoice_vals = {}


            try:
                # _logger.info(json.dumps(ecf_data, indent=4, default=str))
                if l10n_do_ncf_type == '32' and invoice.amount_total_signed < 250000:
                    response = invoice._send_efc_submit_request(
                        ecf_data, invoice.l10n_do_ecf_edi_file_name

                    )
                else:

                    response = invoice._send_ecf_submit_request(
                        ecf_data, invoice.l10n_do_ecf_edi_file_name

                    )

                consulta_rep = False

                if response.status_code == 200:

                    # DGII return a 'null' as an empty message value. We convert it to
                    # its python similar: None
                    response_text = str(response.text)


                    vals = json.loads(response_text)
                    # raise UserError(_("%s", vals))

                    ecf_xml = b""
                    if "xml" in vals:
                        ecf_xml += str(vals["xml"]).encode("utf-8")

                    if vals:





                        if l10n_do_ncf_type == '32' and invoice.amount_total_signed < 250000:
                            consulta_rep = json.loads(response_text)

                        else:
                            if invoice.l10n_do_ecf_send_state != "contingency" or not invoice.l10n_do_ecf_trackid:
                                # Contingency invoices already have trackid,
                                # security_code and sign_date. Do not overwrite it.
                                invoice_vals.update(
                                    {
                                        "l10n_do_ecf_trackid": vals.get("trackId"),
                                    }
                                )
                            time.sleep(1)
                            consulta_rep = json.loads(self._send_ecf_status_request(vals.get("trackId"), invoice).text)

                        status = consulta_rep['estado'].replace(" ", "")
                        invoice_vals["l10n_do_ecf_send_state"] = ECF_STATE_MAP[status]
                        invoice_vals["l10n_do_ecf_message_status"] = consulta_rep
                        invoice.write(invoice_vals)

                        if status in ("AceptadoCondicional", "Rechazado"):
                            if consulta_rep:
                                invoice.log_error_message(json.dumps(consulta_rep))
                            else:
                                invoice.log_error_message(response_text)

                            if status == "Rechazado":
                                invoice.with_context(
                                    cancelled_by_dgii=True
                                ).button_cancel()
                                invoice.state = "cancel"

                    else:
                        # invoice.l10n_do_ecf_send_state = "service_unreachable"
                        invoice._show_service_unreachable_message()

                elif response.status_code == 503:  # DGII is fucked up
                    invoice.l10n_do_ecf_send_state = "contingency"

                elif response.status_code == 400:  # XSD validation failed
                    msg_body = _("External Service XSD Validation Error:\n\n")
                    response_text = response.text
                    error_message = json.loads(response_text)
                    for msg in list(error_message.get("messages") or []):
                        msg_body += "%s\n" % msg
                    raise ValidationError(response_text)
                elif response.status_code == 401 and invoice.company_id.token_expire <= datetime.now():
                    invoice.company_id.post_semilla_dgii()
                    invoice.send_ecf_data()


                else:  # anything else will be treated as a communication issue
                    # invoice.l10n_do_ecf_send_state = "service_unreachable"
                    invoice._show_service_unreachable_message()

            except requests.exceptions.MissingSchema:
                raise ValidationError(_("Wrong external service URL"))

            except requests.exceptions.ConnectionError:
                # Odoo could not send the request
                invoice.l10n_do_ecf_send_state = "not_sent"

        return True

    def get_track_id_status(self):
        """
        Invoices ecf send status may be pending after first send.
        This function re-check its status and update if needed.
        """
        for invoice in self:

            l10n_do_ncf_type = invoice.get_l10n_do_ncf_type()

            if l10n_do_ncf_type == '32' and invoice.amount_total_signed < 250000:

                try:
                    try:
                        trackid = invoice.l10n_do_ecf_trackid

                        if not trackid:
                            if invoice.company_id.token_expire <= datetime.now():
                                invoice.company_id.post_semilla_dgii()

                            headers = {'Authorization': 'Bearer ' + invoice.company_id.token, }

                            url = "https://fc.dgii.gov.do/%s/ConsultaTrackIds/api/TrackIds/Consulta?RncEmisor=%s&Encf=%s" % \
                                  (invoice.company_id.l10n_do_ecf_service_env, invoice.company_id.vat,
                                   invoice.ref)

                            response = requests.get(url, headers=headers)
                            response_text = str(response.text).replace("null", "None")

                            try:
                                vals = json.loads(response_text)
                                for v in vals:
                                    estado = v.get("estado", False)
                                    if estado == 'Aceptado':
                                        track_id = v.get("trackId", False)
                                        if track_id:
                                            invoice.l10n_do_ecf_trackid = track_id
                                        else:
                                            continue

                            except (ValueError, TypeError):
                                continue

                    except requests.exceptions.ConnectionError:
                        continue

                except requests.exceptions.ConnectionError:
                    continue


            else:
                try:
                    trackid = invoice.l10n_do_ecf_trackid

                    if not trackid:
                        if invoice.company_id.token_expire <= datetime.now():
                            invoice.company_id.post_semilla_dgii()

                        headers = {'Authorization': 'Bearer ' + invoice.company_id.token, }

                        url = "https://ecf.dgii.gov.do/%s/ConsultaTrackIds/api/TrackIds/Consulta?RncEmisor=%s&Encf=%s" % \
                              (invoice.company_id.l10n_do_ecf_service_env, invoice.company_id.vat, invoice.ref)

                        response = requests.get(url, headers=headers)
                        response_text = str(response.text).replace("null", "None")

                        try:
                            vals = json.loads(response_text)
                            for v in vals:
                                estado = v.get("estado", False)
                                if estado == 'Aceptado':
                                    track_id = v.get("trackId", False)
                                    if track_id:
                                        invoice.l10n_do_ecf_trackid = track_id
                                    else:
                                        continue

                        except (ValueError, TypeError):
                            continue

                except requests.exceptions.ConnectionError:
                    continue


    def update_ecf_status(self):
        """
        Invoices ecf send status may be pending after first send.
        This function re-check its status and update if needed.
        """
        for invoice in self:

            l10n_do_ncf_type = invoice.get_l10n_do_ncf_type()

            if l10n_do_ncf_type == '32' and invoice.amount_total_signed < 250000:



                try:
                    ecf_data = base64.b64decode(invoice.l10n_do_ecf_edi_file)

                    response = invoice._send_efc_submit_request(
                        ecf_data, invoice.l10n_do_ecf_edi_file_name

                    )
                    response_text = str(response.text).replace("null", "None")
                    invoice.l10n_do_ecf_message_status = response_text

                    try:
                        vals = json.loads(response_text)
                        status = vals.get("estado", "EnProceso").replace(" ", "")
                        if status in ECF_STATE_MAP:
                            invoice.l10n_do_ecf_send_state = ECF_STATE_MAP[status]
                            if ECF_STATE_MAP[status] in (
                                    "delivered_refused",
                                    "conditionally_accepted",
                            ):
                                invoice.log_error_message(response_text)
                                if ECF_STATE_MAP[status] == "delivered_refused":
                                    invoice.with_context(
                                        cancelled_by_dgii=True
                                    ).button_cancel()
                                    invoice.state = "cancel"
                        else:
                            continue

                    except (ValueError, TypeError):
                        continue

                except requests.exceptions.ConnectionError:
                    continue


            else:
                try:
                    trackid = invoice.l10n_do_ecf_trackid

                    if invoice.company_id.token_expire <= datetime.now():
                        invoice.company_id.post_semilla_dgii()

                    headers = {'Authorization': 'Bearer ' + invoice.company_id.token, }

                    url = "https://ecf.dgii.gov.do/%s/ConsultaResultado/api/Consultas/Estado?TrackId=%s" % \
                          (invoice.company_id.l10n_do_ecf_service_env, trackid)

                    response = requests.get(url, headers=headers)
                    response_text = str(response.text).replace("null", "None")
                    invoice.l10n_do_ecf_message_status = response_text

                    try:
                        vals = json.loads(response_text)
                        status = vals.get("estado", "EnProceso").replace(" ", "")
                        if status in ECF_STATE_MAP:
                            invoice.l10n_do_ecf_send_state = ECF_STATE_MAP[status]
                            if ECF_STATE_MAP[status] in (
                                "delivered_refused",
                                "conditionally_accepted",
                            ):
                                invoice.log_error_message(response_text)
                                if ECF_STATE_MAP[status] == "delivered_refused":
                                    invoice.with_context(
                                        cancelled_by_dgii=True
                                    ).button_cancel()
                                    invoice.state = "cancel"
                        else:
                            continue

                    except (ValueError, TypeError):
                        continue

                except requests.exceptions.ConnectionError:
                    continue

    @api.model
    def check_pending_ecf(self):
        """
        This function is meant to be called from ir.cron. It will update pending ecf
        status.
        """
        if self:
            for rec in self:
                rec.get_track_id_status()
                rec.update_ecf_status()
        else:
            pending_invoices = self.search(
                [
                    ("move_type", "in", ("out_invoice", "out_refund", "in_invoice")),
                    ("l10n_do_ecf_send_state", "in", ("delivered_pending","not_sent")),
                    ("l10n_do_ecf_trackid", "!=", False),
                ]
            )
            pending_invoices.get_track_id_status()
            pending_invoices.update_ecf_status()

    @api.model
    def resend_contingency_ecf(self):
        """
        This function is meant to be called from ir.cron. It will resend all
        contingency invoices
        """

        contingency_invoices = self.search(
            [
                ("move_type", "in", ("out_invoice", "out_refund", "in_invoice")),
                ("l10n_do_ecf_send_state", "=", "contingency"),
                ("is_l10n_do_internal_sequence", "=", True),
            ]
        )
        contingency_invoices.send_ecf_data()

    def _do_immediate_send(self):
        self.ensure_one()

        # Invoices which will receive immediate full or partial payment based on
        # payment terms won't be sent until payment is applied.
        # Note: E41 invoices will be never sent on post. These are sent on payment
        # because this type of ECF must have withholding data included.
        if (
            self.get_l10n_do_ncf_type() == "41"
            and self.company_id.l10n_do_send_ecf_on_payment
        ):
            return False

        return True

    @api.depends(
        "line_ids.debit",
        "line_ids.credit",
        "line_ids.currency_id",
        "line_ids.amount_currency",
        "line_ids.amount_residual",
        "line_ids.amount_residual_currency",
        "line_ids.payment_id.state",
        "l10n_do_ecf_send_state",
    )
    def _compute_amount(self):
        super(AccountMove, self)._compute_amount()
        fiscal_invoices = self.filtered(
            lambda i: i.is_l10n_do_internal_sequence
            and i.is_ecf_invoice
            and i.l10n_do_ecf_send_state
            not in ("delivered_accepted", "conditionally_accepted", "delivered_pending", "delivered_refused")
            and i.payment_state != "not_paid"
        )
        fiscal_invoices.calculate_ecf_data()
        fiscal_invoices.send_ecf_data()
        fiscal_invoices._compute_l10n_do_electronic_stamp()

    def l10n_do_ecf_unreconcile_payments(self):
        self.ensure_one()
        for payment_info in self._get_reconciled_info_JSON_values():
            move_lines = self.env["account.move.line"]
            if payment_info["account_payment_id"]:
                move_lines += (
                    self.env["account.payment"]
                    .browse(payment_info["account_payment_id"])
                    .move_id.line_ids
                )
            else:
                move_lines += (
                    self.env["account.move"].browse(payment_info["payment_id"]).line_ids
                )
            move_lines.with_context(move_id=self.id).remove_move_reconcile()
            self._compute_amount()  # recompute payment_state

    def button_cancel(self):

        for inv in self.filtered(
            lambda i: i.is_ecf_invoice
            and i.is_l10n_do_internal_sequence
            and i.l10n_do_ecf_send_state not in ("not_sent", "to_send")
        ):
            if not self._context.get("cancelled_by_dgii", False):
                raise UserError(_("Error. Only DGII can cancel an Electronic Invoice"))

            if inv.l10n_do_ecf_send_state == "delivered_refused":
                # Because ECF's are automatically cancelled when DGII refuse them,
                # undo payments reconcile before cancelling
                inv.l10n_do_ecf_unreconcile_payments()

        return super(AccountMove, self).button_cancel()

    def button_draft(self):
        if self.filtered(
            lambda i: i.is_ecf_invoice
            and i.is_l10n_do_internal_sequence
            and i.l10n_do_ecf_send_state not in ("not_sent", "to_send")
        ) and not self._context.get("cancelled_by_dgii", False):
            raise UserError(
                _("Error. A sent Electronic Invoice cannot be set to Draft")
            )
        return super(AccountMove, self).button_draft()

    def _post(self,soft=True):

        for move in self:
            if move.l10n_latam_use_documents:
                sequence = move.journal_id.l10n_do_sequence_ids.filtered(
                    lambda seq: seq.l10n_latam_document_type_id == move.l10n_latam_document_type_id)
                if sequence:
                    if sequence.number_next_actual > sequence.max_number_next:
                        raise ValidationError(_(
                            "Los comprobantes el tipo de NCF %s se han agotado,"
                            " el maximo numero disponible actualmente es de %s y el ultimo numeral utilizado fue el "
                            "%s.",
                            move.l10n_latam_document_type_id.name, sequence.max_number_next, sequence.max_number_next))

        for line in self.invoice_line_ids:
            if not line.tax_ids:
                type_tax = 'sale' if line.move_id.move_type in ('out_invoice','out_refund') else 'purchase'
                exempt_tax = self.env['account.tax'].search([('amount','=',0),('type_tax_use','=',type_tax),
                                                             ('amount_type','!=','group'),
                                                             ('company_id','=',line.company_id.id),
                                                             ('description','=','Exento')],limit=1)
                line.write({'tax_ids':[(6,0,exempt_tax.ids)]})

        res = super(AccountMove, self)._post(soft=True)


        fiscal_invoices = self.filtered(
            lambda i: i.is_l10n_do_internal_sequence
            and i.is_ecf_invoice
            and i.l10n_do_ecf_send_state
            not in ("delivered_accepted", "conditionally_accepted", "delivered_pending")
            and i._do_immediate_send()
        )

        fiscal_invoices.calculate_ecf_data()
        fiscal_invoices.send_ecf_data()
        fiscal_invoices._compute_l10n_do_electronic_stamp()

        return res

    @api.model
    def new(self, values={}, origin=None, ref=None):
        if (
                self.l10n_latam_use_documents
                and self.is_ecf_invoice
                and values.get("move_type") in ("out_refund", "in_refund")
        ):
            values["l10n_latam_document_type_id"] = self.env.ref(
                "l10n_do_ecf_invoicing.ecf_credit_note_client"
            ).id

        return super(AccountMove, self).new(values, origin, ref)

    def init(self):  # DO NOT FORWARD PORT
        cancelled_invoices = self.search(
            [
                ("state", "=", "cancel"),
                ("l10n_latam_use_documents", "=", True),
                ("cancellation_type", "!=", False),
                ("l10n_do_cancellation_type", "=", False),
            ]
        )
        for invoice in cancelled_invoices:
            invoice.l10n_do_cancellation_type = invoice.cancellation_type

    def unlink(self):
        if self.filtered(
                lambda inv: inv.is_purchase_document()
                            and inv.l10n_latam_country_code == "DO"
                            and inv.l10n_latam_use_documents
                            and inv.name != "/"  # have been posted before
        ):
            raise UserError(
                _("You cannot delete fiscal invoice which have been posted before")
            )
        return super(AccountMove, self).unlink()