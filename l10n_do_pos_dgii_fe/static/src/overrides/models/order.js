/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { Order } from "@point_of_sale/app/store/models";

patch(Order.prototype, {
    setup(_defaultObj, options) {
        super.setup(...arguments);
        if (this.pos.config.l10n_do_fiscal_journal) {
            this.itx_dgii_electronic_stamp = this.itx_dgii_electronic_stamp || "";
            this.l10n_do_ecf_security_code = this.l10n_do_ecf_security_code || "";
            this.l10n_do_ecf_sign_date = this.l10n_do_ecf_sign_date || "";
        }
    },

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        if (this.pos.config.l10n_do_fiscal_journal) {
            this.itx_dgii_electronic_stamp = json.itx_dgii_electronic_stamp || "";
            this.l10n_do_ecf_security_code = json.l10n_do_ecf_security_code || "";
            this.l10n_do_ecf_sign_date = json.l10n_do_ecf_sign_date || "";
        }
    },

    export_for_printing() {
        const result = super.export_for_printing(...arguments);
        if (this.pos.config.l10n_do_fiscal_journal) {
            result.itx_dgii_electronic_stamp = this.itx_dgii_electronic_stamp || "";
            result.l10n_do_ecf_security_code = this.l10n_do_ecf_security_code || "";
            result.l10n_do_ecf_sign_date = this.l10n_do_ecf_sign_date || "";
        }
        return result;
    },
});
