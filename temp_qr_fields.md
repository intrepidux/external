# Plan Final de Adaptación: Módulo l10n_do_fix_report_invoice_an para Localización Adel

## Fecha
8 de enero de 2026

## ✅ **Conclusión del Análisis**

Después de revisar la respuesta del API WebPOS, se confirma que **el API ya proporciona la URL completa del QR** en el campo `"qrCode"`. Esto simplifica enormemente la implementación.

### Variables QR - Estado Final
- ✅ `l10n_do_ecf_security_code` (ya disponible en WebPOS)
- ✅ `l10n_do_ecf_sign_date` (ya disponible en WebPOS)
- ✅ `l10n_do_webpos_electronic_stamp` (NUEVO - evita conflicto con espaillatcomercial)

### Descubrimiento Clave
El API WebPOS devuelve:
```json
"qrCode": "https://ecf.dgii.gov.do/eCF/ConsultaTimbre?RncEmisor=102616094&RncComprador=40230164721&ENCF=E320000000005&FechaEmision=17-12-2025&MontoTotal=925000.01&FechaFirma=23-12-2025%2016:11:50&CodigoSeguridad=fvm5Yn"
```

---

## 🎯 **Plan de Implementación Final - Módulos Específicos**

### **Objetivo**
Hacer disponible el campo `l10n_do_webpos_electronic_stamp` para las plantillas QR, aprovechando que el API WebPOS ya genera la URL completa.

### **📁 Módulo 1: `l10n_do_webpos_fe_base`**
**Ubicación:** `adel_doo17/custom/external/l10n_do_webpos_fe_base/`

#### **Archivo 1.1:** `models/account_move_inherit.py`
```python
# Después de l10n_do_ecf_sign_date
l10n_do_webpos_electronic_stamp = fields.Char(
    string="WebPOS Electronic Stamp",
    copy=False,
    help="Sello electrónico QR obtenido del API WebPOS (evita conflicto con espaillatcomercial)"
)
```

#### **Archivo 1.2:** `models/my_xml_data.py`
```python
# En verify_sent_encf(), después de qrL2
if response_data.get('qrCode'):  # QR code completo
    qr_code_full = response_data.get('qrCode')
    invoice_updates['l10n_do_webpos_electronic_stamp'] = qr_code_full
```

### **📁 Módulo 2: `l10n_do_fix_report_invoice_an`**
**Ubicación:** `adel_doo17/custom/external/l10n_do_fix_report_invoice_an/`

#### **Archivo 2.1:** `views/report_invoice_fix.xml`
```xml
<!-- Cambiar herencia de plantilla -->
<template id="report_invoice_document_fix"
          inherit_id="account.report_invoice_document">
```

### **Flujo de Datos Final**
```
API WebPOS → qrCode → l10n_do_webpos_electronic_stamp → Plantilla QR → PDF con QR escaneable
```

---

## 📋 **Checklist de Implementación**

### ✅ **Fase 1: Preparación (COMPLETADA)**
- [x] Analizar respuesta del API WebPOS
- [x] Confirmar que `qrCode` contiene URL completa
- [x] Diseñar implementación mínima

### ✅ **Fase 2: Desarrollo (COMPLETADO - OPCIÓN HÍBRIDA)**
- [x] **Campo Related**: `l10n_do_webpos_electronic_stamp` → `related='xml_data_id.qr_code'` (sin procesamiento)
- [x] **Campos Directos**: `l10n_do_ecf_security_code` y `l10n_do_ecf_sign_date` (con procesamiento)
- [x] Agregar línea para guardar `qrCode` en `my_xml_data.py`
- [x] Cambiar herencia de plantilla a `account.report_invoice_document`
- [x] Actualizar plantilla QR para usar campo WebPOS

### 🧪 **Fase 3: Testing (PENDIENTE)**
- [ ] Instalar módulo
- [ ] Crear factura electrónica
- [ ] Verificar que campo se llena con URL del API
- [ ] Generar reporte PDF con QR funcional

---

## 💡 **Ventajas de esta Solución**

1. **Simplicidad**: Solo 3 cambios mínimos
2. **Confiabilidad**: Usa datos directos del API de DGII
3. **Mantenibilidad**: Sin lógica adicional compleja
4. **Compatibilidad**: Funciona con cualquier localización

---

## 🎉 **Resultado Esperado**

Después de la implementación:
- ✅ Campo `l10n_do_webpos_electronic_stamp` disponible en facturas WebPOS electrónicas
- ✅ QR generado automáticamente por API WebPOS
- ✅ Plantillas QR funcionales en reportes
- ✅ Compatibilidad total con localización Adel
- ✅ Sin conflictos con espaillatcomercial

---

## 📝 **Notas de Implementación**

- El campo `l10n_do_webpos_electronic_stamp` solo se usa para facturas con diario WebPOS
- Se llena automáticamente cuando se verifica la factura con el API
- No requiere computo adicional - el API ya hace todo el trabajo
- Compatible con el flujo existente de `qrL1` y `qrL2`
- Evita conflictos con el campo computado `l10n_do_electronic_stamp` de espaillatcomercial
