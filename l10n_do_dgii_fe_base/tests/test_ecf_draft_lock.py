# -*- coding: utf-8 -*-
import json

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestEcfDraftLock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'E-CF synthetic partner',
            'vat': '130000001',
        })
        income = cls.env['account.account'].search([
            ('company_id', '=', cls.company.id),
            ('internal_group', '=', 'income'),
        ], limit=1)
        cls.journal = cls.env['account.journal'].create({
            'name': 'ECF lock unit test',
            'code': 'TECF',
            'type': 'sale',
            'company_id': cls.company.id,
            'l10n_latam_use_documents': False,
            'is_dgii': True,
        })
        cls._income_account_id = income.id if income else False

    def _create_posted_move(self):
        if not self._income_account_id:
            self.skipTest('No income account')
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Line',
                'quantity': 1,
                'price_unit': 100.0,
                'account_id': self._income_account_id,
            })],
        })
        move.action_post()
        move.is_ecf_invoice = True
        return move

    def _xml_log(self, move, **vals):
        defaults = {
            'account_move_id': move.id,
            'name': move.name,
        }
        defaults.update(vals)
        return self.env['itx.xml.data.dgii'].create(defaults)

    def _recepcion_json(self, estado, mensajes, extra=None):
        rec = {'estado': estado, 'mensajes': mensajes}
        if extra:
            rec.update(extra)
        return json.dumps({'dgii_recepcion': rec})

    def test_draft_allowed_without_xml_log(self):
        move = self._create_posted_move()
        move.button_draft()
        self.assertEqual(move.state, 'draft')

    def test_draft_blocked_when_accepted_log(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='procesed',
            dgi_status='Aceptado',
        )
        with self.assertRaises(UserError):
            move.button_draft()

    def test_draft_blocked_when_conditionally_accepted(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='sent',
            dgi_status='Aceptado Condicional',
        )
        with self.assertRaises(UserError):
            move.button_draft()

    def test_draft_blocked_when_in_process(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='sent',
            dgi_status='En Proceso',
        )
        with self.assertRaises(UserError):
            move.button_draft()

    def test_draft_blocked_on_1209_json(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='error_no_enviado',
            dgi_status='Rechazado',
            dgi_err_msg='1209: Este número de secuencia ya ha sido utilizado.',
            json_response=self._recepcion_json(
                'Rechazado',
                [{'codigo': 1209, 'valor': 'Secuencia ya utilizada'}],
            ),
        )
        with self.assertRaises(UserError):
            move.button_draft()

    def test_draft_blocked_on_1209_err_msg(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='error_no_enviado',
            dgi_status='Rechazado',
            dgi_err_msg='1209: Este número de secuencia ya ha sido utilizado.',
        )
        with self.assertRaises(UserError):
            move.button_draft()

    def test_draft_allowed_content_rejection_err_msg(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='error_no_enviado',
            dgi_status='Rechazado',
            dgi_err_msg='615: monto en pesos invalido',
        )
        move.button_draft()
        self.assertEqual(move.state, 'draft')

    def test_draft_allowed_615_with_secuencia_utilizada_in_json(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='error_no_enviado',
            dgi_status='Rechazado',
            dgi_err_msg='615: NCF modificado invalido',
            json_response=self._recepcion_json(
                'Rechazado',
                [{
                    'codigo': 615,
                    'valor': 'El monto total no coincide con el comprobante modificado.',
                }],
                extra={'secuenciaUtilizada': True},
            ),
        )
        self.assertFalse(move.itx_ecf_lock_draft)
        move.button_draft()
        self.assertEqual(move.state, 'draft')

    def test_draft_allowed_615_json_without_secuencia_flag(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='error_no_enviado',
            dgi_status='Rechazado',
            json_response=self._recepcion_json(
                'Rechazado',
                [{'codigo': 615, 'valor': 'Referencia invalida.'}],
            ),
        )
        move.button_draft()
        self.assertEqual(move.state, 'draft')

    def test_draft_blocked_unparseable_response(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='error_no_enviado',
            dgi_status='',
            json_response='not-json{{{',
        )
        with self.assertRaises(UserError):
            move.button_draft()

    def test_draft_bypass_with_group_and_reason(self):
        move = self._create_posted_move()
        self._xml_log(
            move,
            status='procesed',
            dgi_status='Aceptado',
        )
        group = self.env.ref('l10n_do_dgii_fe_base.group_ecf_draft_bypass')
        self.env.user.write({'groups_id': [(4, group.id)]})
        move.with_context(
            ecf_draft_bypass=True,
            ecf_draft_bypass_reason='Corrección NC de prueba',
        ).button_draft()
        self.assertEqual(move.state, 'draft')
        self.assertTrue(
            any('Omisión del bloqueo e-CF' in (m.body or '') for m in move.message_ids)
        )