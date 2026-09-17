from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestWebposLineTaxSerialize(TransactionCase):
    """Payload tax fields sent to WebPOS API (ITBIS billing only)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Move = cls.env['account.move']
        cls.itbis_group = cls.env['account.tax.group'].search([('name', '=', 'ITBIS')], limit=1)
        cls.isr_group = cls.env['account.tax.group'].search([('name', '=', 'ISR')], limit=1)
        if not cls.itbis_group:
            cls.itbis_group = cls.env['account.tax.group'].create({'name': 'ITBIS', 'country_id': cls.env.ref('base.do').id})

    def _create_tax(self, name, amount, group, webpos_code='0'):
        return self.env['account.tax'].create({
            'name': name,
            'amount': amount,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'tax_group_id': group.id,
            'tipo_impuesto_webpos': webpos_code,
        })

    def test_exempt_itbis_includes_webpos_codes(self):
        tax = self._create_tax('ITBIS Exento Test', 0.0, self.itbis_group, '0')
        data = self.Move._webpos_serialize_line_tax(tax)
        self.assertEqual(data['tax_group_name'], 'ITBIS')
        self.assertEqual(data['tipo_impuesto_webpos'], '0')
        self.assertEqual(data['tipo_impuesto_webpos_itbis'], '0')

    def test_itbis_18_includes_webpos_codes(self):
        tax = self._create_tax('18% ITBIS Test', 18.0, self.itbis_group, '1')
        data = self.Move._webpos_serialize_line_tax(tax)
        self.assertEqual(data['tipo_impuesto_webpos'], '1')
        self.assertEqual(data['tipo_impuesto_webpos_itbis'], '1')

    def test_itbis_retencion_omits_webpos_codes(self):
        tax = self._create_tax('ITBIS Retenido Test', -10.0, self.itbis_group, '0')
        data = self.Move._webpos_serialize_line_tax(tax)
        self.assertEqual(data['tax_group_name'], 'ITBIS')
        self.assertNotIn('tipo_impuesto_webpos', data)
        self.assertNotIn('tipo_impuesto_webpos_itbis', data)

    def test_non_itbis_tax_omits_webpos_codes(self):
        if not self.isr_group:
            self.skipTest('ISR tax group not installed')
        tax = self._create_tax('ISR Test', 10.0, self.isr_group, '0')
        data = self.Move._webpos_serialize_line_tax(tax)
        self.assertEqual(data['tax_group_name'], 'ISR')
        self.assertNotIn('tipo_impuesto_webpos', data)
        self.assertNotIn('tipo_impuesto_webpos_itbis', data)
