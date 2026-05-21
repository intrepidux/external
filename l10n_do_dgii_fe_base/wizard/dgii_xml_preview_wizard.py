#!/usr/bin/env python3
"""
DGII XML Preview Wizard

Allows users to preview generated XML before sending to DGII.
Shows validation results and errors from XSD validation.
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
import json
import requests
import logging

_logger = logging.getLogger(__name__)


class DGIIXmlPreviewWizard(models.TransientModel):
    _name = 'dgii.xml.preview.wizard'
    _description = 'DGII XML Preview Wizard'
    
    # Related record
    invoice_id = fields.Many2one(
        'account.move',
        string='Factura',
        required=True,
        readonly=True
    )
    
    # XML Content
    xml_content = fields.Text(
        string='XML Generado',
        readonly=True
    )
    
    xml_valid = fields.Boolean(
        string='XML Válido',
        readonly=True
    )
    
    validation_errors = fields.Text(
        string='Errores de Validación',
        readonly=True
    )
    
    validation_errors_count = fields.Integer(
        string='Cantidad de Errores',
        readonly=True
    )
    
    # Status information
    status_message = fields.Char(
        string='Mensaje de Estado',
        readonly=True
    )
    
    environment = fields.Char(
        string='Entorno',
        readonly=True,
        default='test'
    )
    
    can_send = fields.Boolean(
        string='Puede Enviar',
        compute='_compute_can_send',
        store=False
    )
    
    @api.depends('xml_valid', 'validation_errors_count')
    def _compute_can_send(self):
        for record in self:
            record.can_send = record.xml_valid and record.validation_errors_count == 0
    
    def _get_api_base_url(self):
        """Get API base URL from configuration."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'dgii_api.base_url', 
            'http://localhost:8069'
        )
    
    def action_preview_xml(self):
        """
        Genera XML vía el mismo endpoint unificado que el flujo principal (JSON-RPC).
        """
        self.ensure_one()
        
        if not self.invoice_id:
            raise UserError(_('No se ha seleccionado una factura.'))
        
        invoice = self.invoice_id
        try:
            invoice_data = invoice._prepare_invoice_data_for_api(invoice)
            type_document = invoice.doc_type_E(invoice)
            
            cre = invoice.company_id.fe_dgii_id.filtered(lambda p: p.active)[:1]
            if not cre:
                raise UserError(_('Configure un registro activo en Maestro FE DGII.'))
            result = cre._api_jsonrpc(
                'generate_xml',
                cre._api_params_with_auth({
                    'invoice_data': invoice_data,
                    'type_document': type_document,
                }),
                use_api_key=not cre._use_legacy_cert_in_request(),
                timeout=30,
            )
            self.xml_content = result.get('xml_content') or ''
            ok = bool(result.get('success')) and bool(self.xml_content)
            self.xml_valid = ok
            
            cre = invoice.company_id.fe_dgii_id.filtered(lambda p: p.active)[:1]
            self.environment = cre.dgii_client_mode if cre else 'dgii/v1'
            
            errors = []
            if result.get('error'):
                errors.append(result['error'])
            if not ok and not errors:
                errors.append(_('Sin XML en la respuesta'))
            
            self.validation_errors_count = len(errors)
            if errors:
                self.validation_errors = json.dumps(errors, indent=2, ensure_ascii=False)
                self.status_message = _('Error: %s') % errors[0]
            else:
                self.validation_errors = ''
                self.status_message = _('XML generado correctamente')
            
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'dgii.xml.preview.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }
            
        except requests.RequestException as e:
            raise UserError(_('Error de conexión con la API: %s') % str(e))
        except Exception as e:
            _logger.error("Error generando preview: %s", str(e), exc_info=True)
            raise UserError(_('Error generando preview: %s') % str(e))
    
    def action_send_to_dgii(self):
        """
        Send the invoice to DGII (production endpoint).
        Only available if XML is valid.
        """
        self.ensure_one()
        
        if not self.can_send:
            raise UserError(_('No se puede enviar: el XML tiene errores de validación.'))
        
        # Call the actual send method on the invoice
        return self.invoice_id.action_send_dgii()
    
    def action_close(self):
        """Close the wizard."""
        return {'type': 'ir.actions.act_window_close'}
    
    def action_download_xml(self):
        """Download the generated XML file."""
        self.ensure_one()
        
        if not self.xml_content:
            raise UserError(_('No hay contenido XML para descargar.'))
        
        # Create attachment for download
        filename = f"preview_{self.invoice_id.name or 'invoice'}.xml"
        
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(self.xml_content.encode('utf-8')),
            'mimetype': 'application/xml',
            'res_model': 'dgii.xml.preview.wizard',
            'res_id': self.id,
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }


class AccountMove(models.Model):
    _inherit = 'account.move'
    
    def action_preview_dgii_xml(self):
        """
        Open the XML preview wizard.
        Called from the invoice form view.
        """
        self.ensure_one()
        
        # Create wizard record
        wizard = self.env['dgii.xml.preview.wizard'].create({
            'invoice_id': self.id,
        })
        
        # Generate preview
        return wizard.action_preview_xml()
    
    def action_send_dgii(self):
        """
        Send invoice to DGII.
        This would call the production API endpoint.
        """
        self.ensure_one()
        
        # Get or create XML data record
        xml_data_record = self.env['itx.xml.data.dgii'].search([
            ('account_move_id', '=', self.id)
        ], limit=1)
        
        if not xml_data_record:
            xml_data_record = self.env['itx.xml.data.dgii'].create({
                'name': self.name,
                'account_move_id': self.id,
                'company_id': self.company_id.id,
                'status': 'pending',
            })
        
        # Call send method
        xml_data_record.save_and_send_xml()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Envío DGII'),
                'message': _('Factura enviada a DGII. Track ID: %s') % xml_data_record.track_id,
                'sticky': False,
                'type': 'success',
            }
        }
