from odoo import SUPERUSER_ID, api


def _table_exists(cr, table_name):
    cr.execute("SELECT to_regclass(%s)", (table_name,))
    result = cr.fetchone()
    return bool(result and result[0])


def _column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table_name, column_name),
    )
    return bool(cr.fetchone())


def _backfill_payment_mean(cr, table_name, payment_mean_id):
    if not (
        payment_mean_id
        and _table_exists(cr, table_name)
        and _column_exists(cr, table_name, "payment_mean_id")
    ):
        return

    cr.execute(
        f"""
        UPDATE {table_name}
           SET payment_mean_id = %s
         WHERE payment_mean_id IS NULL
        """,
        (payment_mean_id,),
    )


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    payment_mean = env["l10n_co_payroll.payment_mean"].search([("codigo_dian", "=", "10")], limit=1)

    _backfill_payment_mean(cr, "hr_payslip", payment_mean.id)
    _backfill_payment_mean(cr, "hr_payslip_electronic", payment_mean.id)
