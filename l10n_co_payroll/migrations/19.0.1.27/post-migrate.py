from odoo import SUPERUSER_ID, api, fields


LEAVE_TYPE_DEFINITIONS = (
    ("VAC", "Vacaciones", True, "both", False),
    ("LICENCIANR", "Licencia No Remunerada", False, "both", True),
    ("LICENCIAR", "Licencia Remunerada", False, "both", False),
    ("INCCOMUN", "Incapacidad Comun", False, "hr", False),
    ("INCCOMUNSE", "Incapacidad Comun SENA", False, "hr", False),
    ("INCLABORAL", "Incapacidad Laboral", False, "hr", False),
    ("INCPROF", "Incapacidad Profesional", False, "hr", False),
    ("LICMP", "Licencia Maternidad/Paternidad", False, "no_validation", False),
    ("HUELGA_LEGAL", "Huelga Legal", False, "hr", True),
    ("SUSP_CONTRATO", "Suspension de Contrato", False, "hr", True),
)


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


def _ensure_leave_types(env):
    leave_type_by_code = {}
    LeaveType = env["hr.leave.type"].with_context(active_test=False)
    for code, name, requires_allocation, validation_type, unpaid in LEAVE_TYPE_DEFINITIONS:
        work_entry_type = env["hr.work.entry.type"].search([("code", "=", code)], limit=1)
        if not work_entry_type:
            continue
        leave_type = LeaveType.search([("work_entry_type_id", "=", work_entry_type.id)], limit=1)
        values = {
            "name": name,
            "requires_allocation": requires_allocation,
            "leave_validation_type": validation_type,
            "allocation_validation_type": "hr",
            "time_type": "leave",
            "request_unit": "day",
            "unpaid": unpaid,
        }
        if leave_type:
            leave_type.write(values)
        else:
            leave_type = LeaveType.create({"work_entry_type_id": work_entry_type.id, **values})
        leave_type_by_code[code] = leave_type
    return leave_type_by_code


def _backfill_contract_id(cr, table_name, date_expression):
    if not (
        _table_exists(cr, table_name)
        and _table_exists(cr, "hr_employee")
        and _table_exists(cr, "hr_version")
        and _column_exists(cr, table_name, "employee_id")
        and _column_exists(cr, table_name, "contract_id")
        and _column_exists(cr, "hr_employee", "current_version_id")
        and _column_exists(cr, "hr_version", "contract_date_start")
        and _column_exists(cr, "hr_version", "contract_date_end")
    ):
        return

    cr.execute(
        f"""
        WITH contract_map AS (
            SELECT target.id,
                   COALESCE(
                       (
                           SELECT version.id
                             FROM hr_version version
                            WHERE version.employee_id = target.employee_id
                              AND COALESCE(version.contract_date_start, DATE '1900-01-01') <= {date_expression}
                              AND COALESCE(version.contract_date_end, DATE '9999-12-31') >= {date_expression}
                            ORDER BY COALESCE(version.contract_date_start, DATE '1900-01-01') DESC, version.id DESC
                            LIMIT 1
                       ),
                       emp.current_version_id,
                       (
                           SELECT version.id
                             FROM hr_version version
                            WHERE version.employee_id = target.employee_id
                            ORDER BY COALESCE(version.contract_date_start, DATE '1900-01-01') DESC, version.id DESC
                            LIMIT 1
                       )
                   ) AS contract_id
              FROM {table_name} target
              JOIN hr_employee emp
                ON emp.id = target.employee_id
             WHERE target.employee_id IS NOT NULL
               AND target.contract_id IS NULL
        )
        UPDATE {table_name} target
           SET contract_id = contract_map.contract_id
          FROM contract_map
         WHERE target.id = contract_map.id
           AND contract_map.contract_id IS NOT NULL
        """
    )


def _copy_default_vacation_allocations(env, vac_leave_type):
    if not vac_leave_type:
        return

    Allocation = env["hr.leave.allocation"].with_context(active_test=False)
    allocations = Allocation.search(
        [
            ("holiday_status_id.work_entry_type_id.code", "=", "LEAVE120"),
            ("employee_id", "!=", False),
            ("state", "not in", ("cancel", "refuse")),
        ]
    )

    for allocation in allocations:
        employee = allocation.employee_id
        contract = allocation.contract_id or employee._l10n_co_payroll_get_active_contract()
        if not contract:
            contract = employee._l10n_co_payroll_get_contracts(include_inactive=True)[:1]
        if not contract:
            continue

        contract_start = (
            contract._l10n_co_payroll_get_start_date()
            if hasattr(contract, "_l10n_co_payroll_get_start_date")
            else allocation.date_from
        )
        reference_date = allocation.date_from or fields.Date.context_today(env.user)
        nextcall = (
            contract._l10n_co_payroll_get_vacation_nextcall(reference_date)
            if hasattr(contract, "_l10n_co_payroll_get_vacation_nextcall")
            else False
        )
        target = Allocation.search(
            [
                ("employee_id", "=", employee.id),
                ("contract_id", "=", contract.id),
                ("holiday_status_id", "=", vac_leave_type.id),
                ("state", "not in", ("cancel", "refuse")),
            ],
            limit=1,
        )
        if target:
            values = {}
            if not target.date_from and contract_start:
                values["date_from"] = contract_start
            if not target.nextcall and nextcall:
                values["nextcall"] = nextcall
            if not target.contract_id:
                values["contract_id"] = contract.id
            if values:
                target.write(values)
            if allocation.state == "validate" and target.state == "confirm":
                target._action_validate()
            continue

        target = Allocation.create(
            {
                "name": allocation.name.replace("Paid Time Off", "Vacaciones") if allocation.name else "Vacaciones",
                "holiday_status_id": vac_leave_type.id,
                "employee_id": employee.id,
                "contract_id": contract.id,
                "allocation_type": "accrual",
                "date_from": contract_start or reference_date,
                "number_of_days": allocation.number_of_days,
                "state": "confirm",
                "anticipated_vacations": 0.0,
                "nextcall": nextcall,
            }
        )
        if allocation.state == "validate":
            target._action_validate()


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    leave_type_by_code = _ensure_leave_types(env)
    _backfill_contract_id(cr, "hr_leave_allocation", "COALESCE(target.date_from, CURRENT_DATE)")
    _backfill_contract_id(cr, "hr_leave", "COALESCE(target.request_date_from, target.date_from::date, CURRENT_DATE)")
    _copy_default_vacation_allocations(env, leave_type_by_code.get("VAC"))
