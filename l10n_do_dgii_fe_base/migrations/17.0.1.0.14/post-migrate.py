import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Corrige nombres sin .xml para evitar descarga con extensión .xsl (mimetypes Python)."""
    cr.execute("""
        SELECT id, name
        FROM itx_xml_data_dgii
        WHERE name IS NULL
           OR TRIM(name) = ''
           OR LOWER(name) NOT LIKE '%.xml'
    """)
    rows = cr.fetchall()
    if not rows:
        return

    updated = 0
    for row_id, name in rows:
        raw = (name or '').strip()
        if not raw:
            new_name = 'document.xml'
        elif raw.lower().endswith('.xml'):
            continue
        elif raw.lower().endswith('.xsl'):
            new_name = f'{raw[:-4]}.xml'
        else:
            new_name = f'{raw}.xml'
        cr.execute(
            "UPDATE itx_xml_data_dgii SET name = %s WHERE id = %s",
            (new_name, row_id),
        )
        updated += 1

    _logger.info(
        "l10n_do_dgii_fe_base: normalizados %s nombres XML (.xml) en itx.xml.data.dgii",
        updated,
    )
