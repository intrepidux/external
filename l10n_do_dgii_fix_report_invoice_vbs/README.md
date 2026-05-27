# Dominican Republic - Sequence Control and Alerts

## Overview

This Odoo module provides comprehensive control and monitoring of fiscal sequences for Dominican Republic accounting. It helps ensure compliance with fiscal regulations by controlling sequence usage and providing timely alerts when sequences are running low or exhausted.

## Features

### 🔧 Configuration Management
- Configure maximum sequence limits per document type and company
- Set alert thresholds for early warnings
- Assign users for email notifications
- User-friendly interface for sequence management

### 🚨 Visual Alerts
- **Yellow Warning**: Displayed when approaching sequence limits
- **Red Danger**: Displayed when sequences are exhausted
- **Unconfigured Alert**: Shown when sequences are not set up

### 📧 Email Notifications
- Automatic email alerts when sequences reach configured thresholds
- Customizable email templates
- Notifications sent to designated users

### 🚫 Invoice Validation
- Prevents invoice confirmation when sequences are not configured
- Blocks invoice posting when maximum sequences are reached
- Clear error messages guide users to resolution

## Installation

1. Place the module in your Odoo addons directory
2. Update the module list in Odoo
3. Install the module from Apps menu

## Dependencies

- `base`
- `account`
- `l10n_do_accounting`
- `mail`

## Configuration

### Step 1: Access Sequence Configuration

1. Go to **Accounting > Sequence Control > Sequence Max Configuration**
2. Click **Create** to add a new sequence limit

### Step 2: Configure Sequence Limits

For each document type and company, set:

- **Document Type**: Select the fiscal document type (e.g., Invoice, Credit Note)
- **Company**: Choose the company this applies to
- **Maximum Sequences**: Set the maximum allowed sequences
- **Alert Threshold**: Number of remaining sequences that triggers warnings
- **Notification User**: User who will receive email alerts

### Step 3: Save Configuration

Save the record to activate sequence monitoring for that document type.

## Usage

### Creating Invoices

When creating invoices, the system automatically:

1. **Checks sequence configuration** for the document type and company
2. **Calculates remaining sequences** based on current usage
3. **Displays appropriate alerts** in the invoice form
4. **Validates before posting** to prevent unauthorized sequence usage

### Alert Types

#### Yellow Warning Alert
```
⚠️ Quedan X comprobantes disponibles. Considere renovar las secuencias.
```
- Displayed when remaining sequences ≤ alert threshold
- Invoice can still be confirmed
- Email notification sent to configured user

#### Red Danger Alert
```
❌ ¡Las secuencias se han agotado! No se pueden crear más comprobantes de este tipo.
```
- Displayed when remaining sequences ≤ 0
- Invoice confirmation is blocked
- Email notifications sent

#### Unconfigured Alert
```
⚠️ Estas secuencias no han sido configuradas. Por favor, configure el máximo de comprobantes.
```
- Displayed when no sequence configuration exists
- Invoice confirmation is blocked
- Requires administrator setup

## Email Notifications

### Automatic Triggers

Email notifications are sent when:
- Sequences reach the configured alert threshold
- Sequences are completely exhausted
- New sequence configurations are created

### Email Template

The module includes a customizable email template that includes:
- Company information
- Document type details
- Current sequence status
- Urgency indicators

## Security

Access to sequence configuration is controlled through:
- Standard Odoo user groups
- Accounting module permissions
- Administrator-level access for configuration

## Troubleshooting

### Common Issues

#### "External ID not found" Error
- **Cause**: Module folder name doesn't match technical name
- **Solution**: Ensure folder name matches `__manifest__.py` name field

#### No Alerts Displayed
- **Cause**: Sequence configuration missing
- **Solution**: Create sequence limit records for required document types

#### Emails Not Sending
- **Cause**: Mail server not configured or user email missing
- **Solution**: Configure outgoing mail server and user email addresses

### Error Messages

#### Sequence Not Configured
```
No se puede confirmar la factura. Las secuencias para este tipo de documento no han sido configuradas.
```

#### Sequences Exhausted
```
No se puede confirmar la factura. El número máximo de comprobantes ya ha sido alcanzado.
```

## Technical Details

### Models

#### `l10n.sequence.max`
Main configuration model containing:
- Document type references
- Company associations
- Sequence limits and thresholds
- Notification settings

#### Extended `account.move`
Adds computed fields for:
- Current sequence calculations
- Alert level determination
- Validation constraints

### Views

#### Sequence Configuration
- Tree and form views for managing sequence limits
- Integrated into Accounting menu

#### Invoice Form Extension
- Alert banners displayed above invoice content
- Conditional visibility based on sequence status

### Email Templates

#### Sequence Warning Template
- HTML formatted notifications
- Dynamic content based on sequence status
- Company and document type information

## Support

For technical support or questions about this module, please contact:
- **Author**: David Contreras (Garibaldy)
- **Website**: www.intrepidux.com

## Version History

### 17.0.0.0.3
- Enhanced documentation
- Improved error messages
- Better user interface
- Email notification system
- Invoice validation constraints

### 17.0.0.0.2
- Initial sequence control functionality
- Basic alert system
- Configuration interface

### 17.0.0.0.1
- Module creation
- Basic structure setup
