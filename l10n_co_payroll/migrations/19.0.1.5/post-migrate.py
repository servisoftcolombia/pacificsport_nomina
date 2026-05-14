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


def _remap_contract_reference(cr, table_name, column_name):
    if not (
        _table_exists(cr, table_name)
        and _table_exists(cr, "hr_contract")
        and _table_exists(cr, "hr_employee")
        and _table_exists(cr, "hr_version")
        and _column_exists(cr, table_name, column_name)
        and _column_exists(cr, "hr_contract", "employee_id")
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
           SET {column_name} = COALESCE(emp.version_id, latest_version.id)
          FROM hr_contract legacy
          JOIN hr_employee emp
            ON emp.id = legacy.employee_id
          LEFT JOIN latest_version
            ON latest_version.employee_id = emp.id
         WHERE target.{column_name} = legacy.id
           AND COALESCE(emp.version_id, latest_version.id) IS NOT NULL
        """
    )
    cr.execute(
        f"""
        UPDATE {table_name} target
           SET {column_name} = NULL
         WHERE target.{column_name} IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM hr_version version
                WHERE version.id = target.{column_name}
           )
        """
    )


def migrate(cr, version):
    _remap_contract_reference(cr, "new_entry", "contract_id")
    _remap_contract_reference(cr, "historical_withholdings", "contract_id")
    _remap_contract_reference(cr, "intervalo_calendario", "contract_id")
    _remap_contract_reference(cr, "traza_atributo", "id_objeto")

    if _column_exists(cr, "historical_withholdings", "contract_id"):
        cr.execute(
            """
            UPDATE historical_withholdings
               SET contract_id = NULL
             WHERE contract_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                     FROM hr_version version
                    WHERE version.id = historical_withholdings.contract_id
               )
            """
        )
