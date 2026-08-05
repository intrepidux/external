/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

const POLL_ATTEMPTS = 3;
const POLL_DELAY_MS = 1000;

patch(PaymentScreen.prototype, {
    async _postPushOrderResolve(order, orderServerIds) {
        if (this.pos.config.l10n_do_fiscal_journal && order.ncf && orderServerIds?.length) {
            for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt++) {
                try {
                    const result = await this.orm.call(
                        "pos.order",
                        "get_ecf_data_from_invoice",
                        [orderServerIds]
                    );
                    if (result?.itx_dgii_electronic_stamp) {
                        order.itx_dgii_electronic_stamp = result.itx_dgii_electronic_stamp;
                        order.l10n_do_ecf_security_code = result.l10n_do_ecf_security_code || "";
                        order.l10n_do_ecf_sign_date = result.l10n_do_ecf_sign_date || "";
                        break;
                    }
                } catch (error) {
                    console.error("Error polling e-CF data:", error);
                }
                if (attempt < POLL_ATTEMPTS - 1) {
                    await new Promise((resolve) => setTimeout(resolve, POLL_DELAY_MS));
                }
            }
        }
        return super._postPushOrderResolve(...arguments);
    },
});
