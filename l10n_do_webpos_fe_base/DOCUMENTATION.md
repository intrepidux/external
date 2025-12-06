# Documentación: WebPOS Electronic Invoicing API Distinction

## 📋 **Resumen Ejecutivo**

Esta implementación permite distinguir automáticamente las llamadas a la API de facturación electrónica WebPOS basándose en el tipo de diario y los tipos de documentos permitidos, asegurando que solo se procesen vía API los documentos electrónicos autorizados para cada tipo de diario.

## 🎯 **Objetivos**

- **Permitir registro contable**: Cualquier documento puede registrarse para control contable
- **Restringir llamadas API**: Solo documentos permitidos por el diario activan la API electrónica
- **Mantenibilidad**: Configuración automática basada en `journal.l10n_do_document_type_ids`

## 📊 **Tipos de Documentos Electrónicos por Diario**

### **Diarios de Ventas (Sales Journals)**

| Tipo NCF | Código API | Descripción Completa |
|----------|------------|----------------------|
| `e-fiscal` (31) | **FF** | Factura de Crédito Fiscal Electrónica |
| `e-consumer` (32) | **FC** | Factura de Consumo Electrónica |
| `e-debit_note` (33) | **D** | Nota de Débito Electrónica |
| `e-credit_note` (34) | **C** | Nota de Crédito Electrónica |
| `e-special` (44) | **FE** | Régimen Especial Electrónico |
| `e-governmental` (45) | **FG** | Gubernamental Electrónico |
| `e-export` (46) | **FX** | Factura de Exportación Electrónica |

**Total: 7 tipos electrónicos procesables vía API**

### **Diarios de Compras (Purchase Journals)**

| Tipo NCF | Código API | Descripción Completa |
|----------|------------|----------------------|
| `e-informal` (41) | **P** | Comprobante de Compras Electrónico |
| `e-minor` (43) | **E** | Gastos Menores Electrónico |
| `e-exterior` (47) | **PY** | Pagos al Exterior Electrónico |

**Total: 3 tipos electrónicos procesables vía API**

## 🔧 **Implementación Técnica**

### **Lógica de Validación**

```python
# Verificar si el tipo de documento está permitido para el diario
document_type_allowed = False
if invoice.l10n_latam_document_type_id and invoice.journal_id.l10n_do_document_type_ids:
    document_type_allowed = invoice.l10n_latam_document_type_id in invoice.journal_id.l10n_do_document_type_ids

# Solo procesar vía API si está permitido
if (invoice.is_ecf_invoice and invoice.journal_id.is_webpos) and \
   (invoice.l10n_do_fiscal_number and invoice.journal_id.l10n_latam_use_documents) and \
   document_type_allowed:
    # Procesar API call
    execute_EF.save_and_send_xml()
else:
    # Loggear por qué se omitió la llamada API
    _logger.info("WebPOS API call skipped for invoice %s: [reason]", invoice.id)
```

### **Mapeo API Completo**

```python
_API_DOCUMENT_TYPE_MAP = {
    # Electrónicos principales (activos en API)
    'E31': 'FF', 'E32': 'FC', 'E33': 'D', 'E34': 'C',
    'E41': 'P', 'E43': 'E', 'E44': 'FE', 'E45': 'FG',
    'E46': 'FX', 'E47': 'PY',

    # Códigos numéricos equivalentes
    '31': 'FF', '32': 'FC', '33': 'D', '34': 'C',
    '41': 'P', '43': 'E', '44': 'FE', '45': 'FG',
    '46': 'FX', '47': 'PY',

    # Códigos alfanuméricos directos
    'FF': 'FF', 'FC': 'FC', 'D': 'D', 'C': 'C', 'P': 'P',
    'E': 'E', 'FE': 'FE', 'FG': 'FG', 'FX': 'FX', 'PY': 'PY'
}
```

## 📋 **Lista Completa de Tipos Disponibles**

### **Tipos Tradicionales (Serie B)**
- `fiscal` (01) - Comprobante de Crédito Fiscal
- `consumer` (02) - Comprobante para Consumidor Final
- `debit_note` (03) - Nota de Débito
- `credit_note` (04) - Nota de Crédito
- `informal` (11) - Comprobante de Compras
- `unique` (12) - Comprobante Único por Internet
- `minor` (13) - Gastos Menores
- `special` (14) - Régimen Especial
- `governmental` (15) - Gubernamental
- `export` (16) - Exportaciones
- `exterior` (17) - Pagos al Exterior

### **Tipos Electrónicos (Serie E) - Todos Disponibles**
- `e-fiscal` (31) - Factura de Crédito Fiscal Electrónica
- `e-consumer` (32) - Factura de Consumo Electrónica
- `e-debit_note` (33) - Nota de Débito Electrónica
- `e-credit_note` (34) - Nota de Crédito Electrónica
- `e-informal` (41) - Comprobante de Compras Electrónico
- `e-minor` (43) - Gastos Menores Electrónico
- `e-special` (44) - Régimen Especial Electrónico
- `e-governmental` (45) - Gubernamental Electrónico
- `e-export` (46) - Factura de Exportación Electrónica
- `e-exterior` (47) - Pagos al Exterior Electrónico

## 🔍 **Cómo se Filtran los Tipos por Diario**

### **Diarios de Venta**
- Incluyen **todos** los tipos del diccionario `issued`
- Agregan `debit_note` y `credit_note`
- Convierten a versiones electrónicas cuando corresponde

### **Diarios de Compra**
- Incluyen **todos** los tipos del diccionario `received`
- **Excluyen** `fiscal`, `special`, `governmental`
- Convierten a versiones electrónicas cuando corresponde

## 📝 **Bitácora de Implementación**

### **Fase de Análisis**
- ✅ Analizada estructura del módulo `l10n_do_webpos_fe_base`
- ✅ Revisada clasificación de diarios y tipos de documentos en `l10n_do_accounting`
- ✅ Identificado campo `journal.l10n_do_document_type_ids` para validación
- ✅ Definido alcance: permitir registro contable, restringir llamadas API

### **Fase de Implementación**
- ✅ Modificado `action_post()` en `account_move_inherit.py` para validar tipo de documento contra diario
- ✅ Agregado logging detallado para llamadas API omitidas
- ✅ Probado con diferentes combinaciones de diario/documento
- ✅ Documentada lista completa de tipos electrónicos por tipo de diario

### **Fase de Documentación**
- ✅ Actualizada memoria del proyecto (memory bank)
- ✅ Creado archivo `DOCUMENTATION.md` en el módulo
- ✅ Documentado mapeo completo API
- ✅ Incluida bitácora detallada de implementación

## 🚀 **Estado Actual**

**Estado**: ✅ **COMPLETADO**
**Fecha**: Diciembre 2025
**Versión**: 1.0.0

**Funcionalidades Implementadas**:
- ✅ Validación automática de tipos de documento por diario
- ✅ Logging comprehensivo de llamadas API
- ✅ Compatibilidad hacia atrás mantenida
- ✅ Documentación completa incluida

## 🔧 **Configuración del Diario**

Cada diario se configura automáticamente con los tipos de documento permitidos basándose en su tipo (`sale`/`purchase`) y las reglas del módulo `l10n_do_accounting`.

**Ejemplo de configuración automática**:
- Diario de Ventas: incluye E31, E32, E33, E34, E44, E45, E46
- Diario de Compras: incluye E41, E43, E47

## 📞 **Soporte y Mantenimiento**

Para soporte técnico o modificaciones, referirse a:
- Archivo fuente: `models/account_move_inherit.py`
- Método principal: `action_post()`
- Configuración: `journal.l10n_do_document_type_ids`

---

**Nota**: Esta documentación se mantiene automáticamente actualizada con el código fuente del módulo.
