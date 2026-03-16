{
    'name': "Dominican Republic - Sequence Control and Alerts",

    'summary': """
        Control and monitor fiscal sequence usage with alerts and restrictions for Dominican Republic
    """,

    'description': """
        Dominican Republic Fiscal Sequence Control and Alerts
        =====================================================

        This module provides comprehensive control and monitoring of fiscal sequences for Dominican Republic accounting.

        Features:
        ---------
        * Configure maximum sequence limits per document type and company
        * Visual alerts (yellow/red) in invoice forms when approaching or reaching limits
        * Automatic email notifications when sequences are running low
        * Prevent invoice confirmation when sequences are not configured or exhausted
        * User-friendly interface for sequence management

        Usage:
        ------
        1. Go to Accounting > Sequence Control > Sequence Max Configuration
        2. Create records for each document type and company with:
           - Document Type (e.g., Invoice, Credit Note)
           - Company
           - Maximum allowed sequences
           - Alert threshold (when to show warnings)
           - User to notify via email
        3. When creating invoices, the system will:
           - Show yellow warnings when approaching limits
           - Show red alerts when sequences are exhausted
           - Block invoice confirmation if sequences not configured or exhausted
           - Send email notifications automatically

        Alerts:
        -------
        * Yellow Warning: "Quedan X comprobantes disponibles. Considere renovar las secuencias."
        * Red Danger: "¡Las secuencias se han agotado! No se pueden crear más comprobantes de este tipo."
        * Unconfigured: "Estas secuencias no han sido configuradas. Por favor, configure el máximo de comprobantes."

        Email Notifications:
        --------------------
        Automatic email alerts are sent when sequences reach the configured alert threshold,
        notifying the designated user about the need to renew sequences.

        Security:
        ---------
        Access is controlled through standard Odoo security groups. Users need appropriate
        permissions to configure sequence limits and view alerts.
    """,

    'author': "David Contreras (Garibaldy)",
    'website': "https://www.intrepidux.com",
    'category': 'Accounting/Localizations/Account Charts',
    'version': "18.0.1.0.0",
    'depends': ['base', 'account', 'l10n_do_accounting', 'mail', 'l10n_do_fix_report_invoice'],
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'data/mail_template_sequence_warning.xml',
    ],
}