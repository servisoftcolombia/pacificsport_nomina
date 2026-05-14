import calendar
from datetime import date

import odoo
from odoo import SUPERUSER_ID, api, fields
from odoo.modules.registry import Registry
from odoo.service import server as odoo_server
from odoo.tools import config


DB_NAME = "DEMO"
DB_HOST = "db"
DB_PASSWORD = "odoo"
CONFIG_FILE = "/etc/odoo/odoo.conf"
env = None

VALIDATION_TRACE_VARIABLES = {
    2025: {
        "smlv": 1423500,
        "aux_trans": 200000,
        "valor_uvt": 49799,
    },
    2026: {
        "smlv": 1750905,
        "aux_trans": 249095,
        "valor_uvt": 53343,
    },
}


class _RollbackTest(Exception):
    pass


def _ensure_validation_trace_variable(reference_date):
    trace_variable = env["traza.variable"].search(
        [
            ("fecha_desde", "<=", reference_date),
            ("fecha_hasta", ">=", reference_date),
        ],
        limit=1,
    )
    if trace_variable:
        return trace_variable

    values = VALIDATION_TRACE_VARIABLES.get(reference_date.year)
    if not values:
        raise RuntimeError(f"Missing validation trace variable defaults for year {reference_date.year}")

    trace_variable = env["traza.variable"].create(
        {
            "fecha_desde": date(reference_date.year, 1, 1),
            "fecha_hasta": date(reference_date.year, 12, 31),
            "smlv": values["smlv"],
            "smilv": values["smlv"] * 13,
            "aux_trans": values["aux_trans"],
            "valor_uvt": values["valor_uvt"],
        }
    )
    print(
        "TRACE_VARIABLE_TEMP",
        trace_variable.id,
        trace_variable.fecha_desde,
        trace_variable.fecha_hasta,
        trace_variable.smlv,
        trace_variable.aux_trans,
        trace_variable.valor_uvt,
    )
    return trace_variable


def _get_struct(contract):
    return (
        contract.structure_id
        or contract.structure_type_id.default_struct_id
        or env["hr.payroll.structure"].search(
            [("company_id", "in", [False, contract.company_id.id])],
            limit=1,
        )
    )


def _current_month_period(reference_date):
    last_day = calendar.monthrange(reference_date.year, reference_date.month)[1]
    return reference_date.replace(day=1), reference_date.replace(day=last_day)


def _get_active_contract(reference_date):
    period_start, period_end = _current_month_period(reference_date)
    allocations = env["hr.leave.allocation"].search(
        [
            ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
            ("state", "=", "validate"),
            ("contract_id", "!=", False),
        ],
        order="id",
    )
    for allocation in allocations:
        contract = allocation.contract_id
        if contract.state != "open":
            continue
        overlapping = env["hr.payslip"].search_count(
            [
                ("employee_id", "=", allocation.employee_id.id),
                ("date_from", "<=", period_end),
                ("date_to", ">=", period_start),
                ("state", "!=", "cancel"),
            ]
        )
        if not overlapping:
            return contract
    return allocations[:1].contract_id


def _get_definitive_contract(reference_date):
    return env["hr.version"].search(
        [
            ("employee_id", "!=", False),
            ("tipo_salario", "in", ("tradicional", "integral")),
            ("contract_date_end", "!=", False),
            ("contract_date_end", "<", reference_date),
        ],
        order="contract_date_end desc, id desc",
        limit=1,
    )


def _ensure_vacation_allocation(contract, reference_date):
    allocation = env["hr.leave.allocation"].search(
        [
            ("employee_id", "=", contract.employee_id.id),
            ("contract_id", "=", contract.id),
            ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
            ("state", "not in", ("cancel", "refuse")),
        ],
        limit=1,
    )
    if allocation:
        if allocation.state == "confirm":
            allocation._action_validate()
        return allocation

    leave_type = env["hr.leave.type"].search([("work_entry_type_id.code", "=", "VAC")], limit=1)
    allocation = env["hr.leave.allocation"].create(
        {
            "name": f"Vacaciones {contract.employee_id.name}",
            "holiday_status_id": leave_type.id,
            "employee_id": contract.employee_id.id,
            "contract_id": contract.id,
            "allocation_type": "accrual",
            "date_from": contract._l10n_co_payroll_get_start_date() or reference_date,
            "number_of_days": 15.0,
            "state": "confirm",
            "nextcall": contract._l10n_co_payroll_get_vacation_nextcall(reference_date),
        }
    )
    allocation._action_validate()
    return allocation


def _run_liquidation(contract, liquidation, date_from, date_to, ensure_vacation=False):
    employee = contract.employee_id
    struct = _get_struct(contract)
    if not struct:
        print(f"{liquidation}: ERROR missing payroll structure for contract {contract.id}")
        return

    try:
        with env.cr.savepoint():
            _ensure_validation_trace_variable(date_to)
            if ensure_vacation:
                _ensure_vacation_allocation(contract, date_to)

            payslip = env["hr.payslip"].create(
                {
                    "name": f"TMP {liquidation} {employee.name}",
                    "employee_id": employee.id,
                    "version_id": contract.id,
                    "company_id": contract.company_id.id,
                    "struct_id": struct.id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "liquidar_por": liquidation,
                }
            )
            payslip._onchange_employee()
            payslip.compute_sheet()
            net = sum(payslip.line_ids.filtered(lambda line: line.code == "NET").mapped("total"))
            print(
                f"{liquidation}: OK employee={employee.id} contract={contract.id} "
                f"state={payslip.state} lines={len(payslip.line_ids)} "
                f"worked_days={len(payslip.worked_days_line_ids)} net={round(net, 2)}"
            )
            raise _RollbackTest
    except _RollbackTest:
        return
    except Exception as err:
        print(f"{liquidation}: ERROR employee={employee.id} contract={contract.id} {type(err).__name__}: {err}")


def main():
    global env

    config.parse_config(
        [
            "-c",
            CONFIG_FILE,
            "-d",
            DB_NAME,
            "--db_host",
            DB_HOST,
            "--db_password",
            DB_PASSWORD,
        ]
    )
    odoo_server.load_server_wide_modules()
    registry = Registry(DB_NAME)

    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        today = fields.Date.context_today(env.user)
        period_start, period_end = _current_month_period(today)

        active_contract = _get_active_contract(today)
        definitive_contract = _get_definitive_contract(today)

        print(
            "ACTIVE_CONTRACT",
            getattr(active_contract, "id", False),
            getattr(getattr(active_contract, "employee_id", False), "name", False),
            getattr(active_contract, "state", False),
        )
        print(
            "DEFINITIVE_CONTRACT",
            getattr(definitive_contract, "id", False),
            getattr(getattr(definitive_contract, "employee_id", False), "name", False),
            getattr(definitive_contract, "state", False),
        )

        if active_contract:
            for liquidation in ("nomina", "vacaciones", "cesantias", "intereses_cesantias"):
                _run_liquidation(active_contract, liquidation, period_start, period_end, ensure_vacation=True)

        if definitive_contract:
            contract_end = definitive_contract._l10n_co_payroll_get_end_date() or period_end
            definitive_start = contract_end.replace(day=1)
            _run_liquidation(definitive_contract, "definitiva", definitive_start, contract_end, ensure_vacation=True)

        cr.rollback()


if __name__ == "__main__":
    main()
