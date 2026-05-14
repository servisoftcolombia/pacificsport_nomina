from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    journals = env["account.journal"].with_context(active_test=False).search(
        [
            ("default_account_id", "!=", False),
            "|",
            ("default_debit_discount_id", "=", False),
            ("default_credit_discount_id", "=", False),
        ]
    )
    for journal in journals:
        vals = {}
        if not journal.default_debit_discount_id:
            vals["default_debit_discount_id"] = journal.default_account_id.id
        if not journal.default_credit_discount_id:
            vals["default_credit_discount_id"] = journal.default_account_id.id
        if vals:
            journal.write(vals)
