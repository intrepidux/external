                'currency_id': {
                    'id': invoice.currency_id.id,
                    'name': invoice.currency_id.name,
                    'decimal_places': invoice.currency_id.decimal_places,
                    'inverse_rate': invoice.currency_id.inverse_rate,
                },
                'company_id': {
                    'fe_webpos_id': self._serialize_datetime_data(invoice.company_id.fe_webpos_id.read()) if invoice.company_id.fe_webpos_id else [],
                },
                'invoice_payments_widget': self._serialize_datetime_data(invoice.invoice_payments_widget),
                'payment_ids': self._serialize_datetime_data(invoice.payment_ids.read()) if invoice.payment_ids else [],
                'l10n_do_origin_ncf': invoice.l10n_do_origin_ncf,
                'debit_origin_id': invoice.debit_origin_id.id if invoice.debit_origin_id else False,
                'withholded_itbis': getattr(invoice, 'withholded_itbis', 0.0),
                'income_withholding': getattr(invoice, 'income_withholding', 0.0),
                'aditional_info_invoice_header1': getattr(invoice, 'aditional_info_invoice_header1', ''),
                'aditional_info_invoice_header2': getattr(invoice, 'aditional_info_invoice_header2', ''),
            },
            'lines': processed_lines,
            'origin_document_data': False,
            'current_user_login_data': False,
        }

        type_document = self.doc_type_E(self.name)

        payload = {
            'jsonrpc': '2.0',
            'method': 'call',
            'params': {
                'invoice_data': self._serialize_datetime_data(invoice_data_payload),
                'type_document': type_document,
            },
            'id': self.id or 1,
        }

        headers = {'Content-Type': 'application/json'}

        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            response_jsonrpc = response.json()

            if 'error' in response_jsonrpc:
                error_details = response_jsonrpc['error']
                _logger.error('API returned JSON-RPC error: %s', error_details)
                raise UserError(_('API Error: %s') % error_details.get('message', 'Unknown JSON-RPC error'))

            response_data = response_jsonrpc.get('result')

            if not response_data:
                _logger.error('No result data in API response: %s', response_jsonrpc)
                raise UserError(_('No result data received from XML generation API'))

            if response_data.get('xml_content'):
                self.xml_data = response_data['xml_content']
                _logger.info("XML generated successfully by webpos_api for record: %s", self.name)
                    
            elif response_data.get('error'):
                error_message = response_data['error']
                _logger.error('Error generating XML via webpos_api: %s', error_message)
                raise UserError(_('Error generating XML: %s') % error_message)
            else:
                _logger.error('Unexpected API response format: %s', response_data)
                raise UserError(_('Unexpected response format from XML generation API'))

        except requests.exceptions.Timeout:
            _logger.error('Timeout communicating with webpos_api')
            raise UserError(_('Timeout error: XML generation API did not respond within 30 seconds'))
        except requests.exceptions.ConnectionError:
            _logger.error('Connection error communicating with webpos_api at %s', api_url)
            raise UserError(_('Connection error: Could not connect to XML generation API at %s') % api_url)
        except requests.exceptions.RequestException as e:
            _logger.error('Error communicating with webpos_api: %s', str(e))
            raise UserError(_('Error communicating with XML generation API: %s') % str(e))
        except json.JSONDecodeError as e:
            _logger.error('Invalid JSON response from webpos_api: %s', str(e))
            raise UserError(_('Invalid JSON response from XML generation API'))
        except Exception as e:
            _logger.error('An unexpected error occurred during XML generation API call: %s', str(e))
            raise UserError(_('An unexpected error occurred during XML generation: %s') % str(e))

    def test_api_connection(self):
        """Test API connectivity by calling the test endpoint."""
        api_base_url = self.env['ir.config_parameter'].sudo().get_param('webpos_api.base_url', 'http://localhost:8069')
        api_url = f'{api_base_url}/test'
        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            return {"success": True, "message": "Conexion API OK"}
        except requests.ConnectionError:
            return {"success": False, "error": "Error de conexion al API (proxy/red)"}
        except requests.Timeout:
            return {"success": False, "error": "Timeout al conectar con API"}
        except requests.HTTPError as e:
            return {"success": False, "error": f"Error HTTP API: {e}"}
        except Exception as e:
            return {"success": False, "error": f"Error inesperado: {e}"}

    def doc_type_E(self, doc_string):
        if len(doc_string) >= 13:
            result = doc_string[1:3]
            return result
        return "FF"
