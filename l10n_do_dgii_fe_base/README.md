# l10n_do_dgii_fe_base

Módulo cliente de Odoo 17 para integración con API de Facturación Electrónica DGII (República Dominicana).

## Descripción

Este módulo permite a Odoo 17 comunicarse con un servicio API externo para:
- Generar XML de facturación electrónica según normativas DGII
- Validar XML contra esquemas XSD
- Enviar facturas electrónicas a DGII
- Verificar estado de facturas enviadas

## Dependencias

- **base** - Framework base de Odoo
- **account** - Módulo de contabilidad
- **l10n_do** - Localización dominicana de Odoo

## Instalación

1. Copiar el módulo a la carpeta de addons:
```bash
cp -r l10n_do_dgii_fe_base /path/to/odoo/addons/
```

2. Actualizar lista de aplicaciones en Odoo (Modo desarrollador)

3. Buscar "l10n_do_dgii_fe_base" e instalar

## Configuración UI

### 1. Credenciales DGII

Ir a: **Facturación → Configuración → DGII → Credenciales**

#### Campos requeridos:
- **Nombre**: Identificador del ambiente
- **Compañía**: Compañía a la que aplica
- **Activo**: Marcar como activo (solo uno por compañía)

#### Modo de Operación:
- **Modo Prueba**: Valida XML contra XSD sin enviar a DGII real
- **Modo Producción**: Envía facturas reales a DGII (requiere ambiente eCF)

#### Credenciales DGII:
- **RNC**: Registro Nacional de Contribuyentes (9 o 11 dígitos)
- **Certificado Digital**: Archivo .p12 o .pfx
- **Contraseña del Certificado**: Password del archivo
- **Entorno DGII**: CerteCF, TesteCF o eCF (solo aplica en modo producción)

#### URL de la API:
- **URL Base de la API**: Endpoint del servidor API (ej: `http://api-server:8069`)

### 2. Diario Contable

Ir al diario de facturas y activar:
- **Es DGII**: Marcar como `True` para facturas electrónicas

## Uso

### Previsualizar XML (Modo Prueba)

1. Crear una factura en estado "Publicado"
2. Hacer clic en **Previsualizar XML (Test)**
3. El sistema mostrará:
   - XML generado
   - Resultado de validación XSD
   - Errores de validación (si existen)
4. Descargar el XML si la validación es exitosa

### Enviar a DGII (Modo Producción)

1. Asegurarse que la credencial esté en **Modo Producción**
2. La factura debe estar en estado "Publicado"
3. Hacer clic en **Enviar a DGII (Prod)**
4. El sistema enviará la factura y retornará:
   - Track ID para seguimiento
   - XML firmado
   - Estado inicial (generalmente "pending")

### Verificar Estado

Las facturas enviadas pueden verificarse en:
**Facturación → DGII → Registros XML**

## Equivalencias DGII: `tipo_impuesto_dgii` (impuesto) ↔ `IndicadorFacturacion` (XML)

En **account.tax**, `tipo_impuesto_dgii` usa códigos internos **0–6** del módulo `l10n_do_dgii_fe_base`.

En el **XML e-CF**, cada línea lleva **IndicadorFacturacion** con valores XSD **0–4** (tipo de facturación del ítem).

**No son la misma escala**: por ejemplo, en el impuesto **`0` = Exento** mapea a indicador XSD **`4`**; en el impuesto **`4` = No facturable** mapea a indicador XSD **`0`**.

Opcionalmente puede fijarse **`dgii_indicador_facturacion`** en **account.move.line** (o en el JSON/API) con ya el valor **XSD 0–4**; si viene vacío, el generador deduce el indicador desde `tipo_impuesto_dgii` de cada `tax_ids` con la tabla siguiente (implementada en `itx_dgii_api`: `TIPO_IMPUESTO_DGII_TO_INDICADOR`).

| `tipo_impuesto_dgii` | Etiqueta maestro (impuesto) | `IndicadorFacturacion` (XSD / línea manual) |
|----------------------|----------------------------|---------------------------------------------|
| `0` | Exento | **4** |
| `1` | 18% (ITBIS 1) | **1** |
| `2` | 16% (ITBIS 2) | **2** |
| `3` | 0% ITBIS (E46) | **3** |
| `4` | No facturable Hoteles y/o Restaurantes | **0** |
| `5` | 18% + 10% (ITBIS 1 + Ley) | **1** |
| `6` | Exento + 10% (Ley) | **4** |

Con **precio gravado típico** y **solo retenciones** en `tax_ids` (ISR/ITBIS retenido: `tax_ids[].amount` negativo porque es **% del maestro**), ver `dgii_indicador_facturacion_from_line_taxes`: se usa **`tipo_impuesto_dgii` sobre la retención** cuando aplica y no es código `0` de anotación equivocada, o bien **fallback** con `price_subtotal` cuando no clasifica ningún impuesto pero la línea es sólo tasas negativas.

### Líneas sólo con retención (ej. ISR ‑27 % sobre servicio)

El JSON de Odoo usa `tax_ids[].amount` = **porcentaje del maestro** (`account.tax.amount`), por tanto las retenciones son negativas. Si no hay ITBIS + en línea pero la base existe:

- Opción A: **`tipo_impuesto_dgii` en el impuesto de retención** (p.ej. `1`) — el generador usa ese código también con `amount` negativo (**no** usar `0` de relleno para «Exento», se ignora en retención).
- Opción B: sin tipo en impuestos, si vienen **`price_subtotal` > 0** en la línea del payload ⇒ en tipos e-CF habituales **indicador gravado (1)** por defecto; en **TipoeCF 47** (pago al exterior) DGII **sólo permite exento**: el generador normaliza **siempre a indicador 4** (código reg. 244).

**TipoeCF 47:** no hace falta añadir manualmente un impuesto «ITBIS Exempt» solo para que DGII acepte la línea — el XML usa **IndicadorFacturacion 4** y los totales reconcilian `MontoExento` desde las líneas cuando el indicador es 4.

## Estructura de Datos Enviados

El módulo envía los siguientes datos a la API:

```json
{
  "invoice_data": {
    "record": {
      "name": "FACT001",
      "invoice_date": "2024-01-15",
      "l10n_latam_document_number": "E310000000001",
      "partner_id": {
        "name": "Cliente SA",
        "vat": "101123456",
        "street": "Calle Principal 123",
        "email": "cliente@ejemplo.com"
      },
      "company_id": {
        "name": "Mi Empresa",
        "vat": "102345678"
      },
      "currency_id": {
        "name": "DOP",
        "decimal_places": 2
      },
      "l10n_do_origin_ncf": null,
      "withholded_itbis": 0.0,
      "income_withholding": 0.0
    },
    "lines": [
      {
        "name": "Producto A",
        "price_unit": 100.00,
        "quantity": 2,
        "discount": 0,
        "price_subtotal": 200.00,
        "tax_ids": [
          {
            "name": "ITBIS 18%",
            "amount": 18.0,
            "tipo_impuesto_dgii": null
          }
        ]
      }
    ],
    "tax_summary": {
      "base_18": 200.00,
      "itbis_18": 36.00,
      "base_16": 0.0,
      "itbis_16": 0.0,
      "base_0": 0.0,
      "itbis_0": 0.0,
      "exento": 0.0,
      "total_itbis": 36.00,
      "itbis_retenido": 0.0,
      "isr_retenido": 0.0,
      "impuestos_adicionales": []
    },
    "amount_total": 236.00,
    "amount_untaxed": 200.00,
    "amount_tax": 36.00
  },
  "type_document": "31",
  "document_flow": "ECF",
  "certificate_b64": "base64_encoded_certificate...",
  "certificate_password": "cert_password",
  "rnc": "102345678",
  "environment": "TesteCF"
}
```

## Endpoints Consumidos

El módulo cliente consume los siguientes endpoints de la API externa:

### Modo Prueba (`/dgii/test/v1/*`)

| Endpoint | Descripción |
|----------|-------------|
| `POST /dgii/test/v1/preview` | Genera XML y valida contra XSD |
| `POST /dgii/test/v1/submit_invoice` | Simula envío con respuesta mock |
| `POST /dgii/test/v1/check_status` | Simula verificación de estado |
| `POST /dgii/test/v1/test` | Test de conectividad |

### Modo Producción (`/dgii/v1/*`)

| Endpoint | Descripción |
|----------|-------------|
| `POST /dgii/v1/submit_invoice` | Envía factura real a DGII |
| `POST /dgii/v1/check_status` | Verifica estado con DGII |
| `POST /dgii/v1/validate_certificate` | Valida certificado digital |
| `POST /dgii/v1/test` | Test de conectividad |

## Flujo de Estados

```
Por Enviar (pending)
    ↓
Enviado (sent) ←── Track ID recibido
    ↓
Procesado (procesed) ←── Autorizado por DGII
    ↓
Error (error) ←── Rechazado por DGII
```

## Resolución de Problemas

### Error "No hay ambiente activo configurado"
Verificar que existe un registro en Credenciales DGII marcado como Activo.

### Error "No hay certificado digital configurado"
En modo producción, es obligatorio subir un certificado .p12/.pfx válido.

### Error "No hay RNC configurado"
El RNC debe tener 9 o 11 dígitos numéricos.

### Error de conexión API
Verificar que:
1. La URL de la API es accesible desde el servidor Odoo
2. El servidor API está ejecutándose
3. No hay firewalls bloqueando la conexión

### XML inválido según XSD
En modo prueba, usar Previsualizar XML para ver los errores de validación detallados.

## Modelos Principales

- `itx.fe.dgii` - Credenciales y configuración DGII
- `itx.xml.data.dgii` - Registros XML enviados/procesados
- `account.move` - Herencia para botones de envío

## Soporte

Para reportar problemas o solicitar mejoras, contactar al equipo de desarrollo.

## Versión

17.0.1.0.0
