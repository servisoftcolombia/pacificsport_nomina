from odoo import SUPERUSER_ID, api


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


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    if _column_exists(cr, "hr_payslip", "liquidar_por"):
        cr.execute("UPDATE hr_payslip SET liquidar_por = 'nomina' WHERE liquidar_por IS NULL")

    if _column_exists(cr, "hr_employee", "address_home_id") and _column_exists(cr, "hr_employee", "work_contact_id"):
        cr.execute(
            """
            UPDATE hr_employee
               SET address_home_id = work_contact_id
             WHERE address_home_id IS NULL
               AND work_contact_id IS NOT NULL
            """
        )

    if _column_exists(cr, "res_partner", "fe_nit") and _column_exists(cr, "res_partner", "vat"):
        cr.execute(
            """
            UPDATE res_partner
               SET vat = fe_nit
             WHERE (vat IS NULL OR vat = '')
               AND fe_nit IS NOT NULL
               AND fe_nit <> ''
            """
        )

    payment_mean = env["l10n_co_payroll.payment_mean"].search([("codigo_dian", "=", "10")], limit=1)
    if payment_mean and _column_exists(cr, "hr_payslip", "payment_mean_id"):
        cr.execute(
            """
            UPDATE hr_payslip
               SET payment_mean_id = %s
             WHERE payment_mean_id IS NULL
            """,
            (payment_mean.id,),
        )
