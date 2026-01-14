from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WebposResendConfirmationWizard(models.TransientModel):
    _name = 'webpos.resend.confirmation.wizard'
    _description = 'Wizard for confirming WebPOS document resend'

    invoice_ids = fields.Many2many(
        'account.move',
        string='Facturas a Reenviar',
        readonly=True
    )

    message = fields.Text(
        string='Mensaje de Confirmación',
        readonly=True
    )

    def action_confirm_resend(self):
        """Execute the WebPOS resend for selected invoices"""
        self.ensure_one()

        if not self.invoice_ids:
            raise UserError(_('No hay facturas seleccionadas para reenviar.'))

        success_count = 0
        error_messages = []

        for invoice in self.invoice_ids:
            try:
                # Call the manual resend method
                result = invoice.action_manual_resend_webpos()

                if result and result.get('params', {}).get('type') == 'success':
                    success_count += 1
                else:
                    error_messages.append(f"Factura {invoice.name}: Error desconocido")

            except Exception as e:
                error_messages.append(f"Factura {invoice.name}: {str(e)}")

        # Show results
        if success_count == len(self.invoice_ids):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Éxito'),
                    'message': _('Todas las facturas fueron reenviadas exitosamente a WebPOS.'),
                    'type': 'success',
                }
            }
        elif success_count > 0:
            message = _(f'{success_count} de {len(self.invoice_ids)} facturas reenviadas exitosamente.')
            if error_messages:
                message += '\n\n' + _('Errores:') + '\n' + '\n'.join(error_messages[:5])  # Limit to first 5 errors
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Resultado Parcial'),
                    'message': message,
                    'type': 'warning',
                }
            }
        else:
            message = _('No se pudo reenviar ninguna factura.') + '\n\n' + _('Errores:') + '\n' + '\n'.join(error_messages[:10])
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': message,
                    'type': 'danger',
                }
            }

    def action_cancel(self):
        """Cancel the wizard"""
        return {'type': 'ir.actions.act_window_close'}
