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


def _backfill_contract_id(cr, table_name):
    if not (
        _table_exists(cr, table_name)
        and _table_exists(cr, "hr_version")
        and _table_exists(cr, "hr_employee")
        and _column_exists(cr, table_name, "employee_id")
        and _column_exists(cr, table_name, "contract_id")
        and _column_exists(cr, "hr_employee", "version_id")
    ):
        return

    cr.execute(
        f"""
        WITH latest_version AS (
            SELECT DISTINCT ON (employee_id) id, employee_id
              FROM hr_version
             ORDER BY employee_id, COALESCE(contract_date_start, date_start) DESC NULLS LAST, id DESC
        )
        UPDATE {table_name} target
           SET contract_id = COALESCE(emp.version_id, latest_version.id)
          FROM hr_employee emp
          LEFT JOIN latest_version
            ON latest_version.employee_id = emp.id
         WHERE target.employee_id = emp.id
           AND target.contract_id IS NULL
           AND COALESCE(emp.version_id, latest_version.id) IS NOT NULL
        """
    )


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    if _column_exists(cr, "hr_leave_allocation", "saldo"):
        cr.execute("UPDATE hr_leave_allocation SET saldo = FALSE WHERE saldo IS NULL")

    if _column_exists(cr, "hr_leave_allocation", "anticipated_vacations"):
        cr.execute(
            """
            UPDATE hr_leave_allocation
               SET anticipated_vacations = 0
             WHERE anticipated_vacations IS NULL
            """
        )

    if _column_exists(cr, "hr_leave", "remaining_addition"):
        cr.execute(
            """
            UPDATE hr_leave
               SET remaining_addition = 0
             WHERE remaining_addition IS NULL
            """
        )

    _backfill_contract_id(cr, "hr_leave")
    _backfill_contract_id(cr, "hr_leave_allocation")

    if _column_exists(cr, "hr_leave", "number_of_days_calendar"):
        cr.execute(
            """
            UPDATE hr_leave
               SET number_of_days_calendar = ((date_to::date - date_from::date) + 1)
             WHERE number_of_days_calendar IS NULL
               AND date_from IS NOT NULL
               AND date_to IS NOT NULL
            """
        )

    if _table_exists(cr, "book_vacations"):
        cr.execute("DELETE FROM book_vacations")

    env["book.vacations"].generate_book()
