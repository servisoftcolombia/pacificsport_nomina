import calendar
from datetime import date

import odoo
from odoo import SUPERUSER_ID, api
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

JULY_REFERENCE = date(2026, 7, 10)
JANUARY_REFERENCE = date(2026, 1, 10)


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

    values = VALIDATION_TRACE_VARIABLES[reference_date.year]
    return env["traza.variable"].create(
        {
            "fecha_desde": date(reference_date.year, 1, 1),
            "fecha_hasta": date(reference_date.year, 12, 31),
            "smlv": values["smlv"],
            "smilv": values["smlv"] * 13,
            "aux_trans": values["aux_trans"],
            "valor_uvt": values["valor_uvt"],
        }
    )


def _month_period(target_date):
    last_day = calendar.monthrange(target_date.year, target_date.month)[1]
    return target_date.replace(day=1), target_date.replace(day=last_day)


def _get_struct(version):
    return (
        version.structure_id
        or version.structure_type_id.default_struct_id
        or env["hr.payroll.structure"].search(
            [("company_id", "in", [False, version.company_id.id])],
            limit=1,
        )
    )


def _find_candidate_version():
    period_start = date(2025, 7, 1)
    period_end = date(2026, 6, 30)
    versions = env["hr.version"].search(
        [
            ("employee_id", "!=", False),
            ("contract_date_start", "!=", False),
            "|",
            ("contract_date_end", "=", False),
            ("contract_date_end", ">=", period_end),
        ],
        order="contract_date_start, id",
    )
    for version in versions:
        if not _get_struct(version):
            continue
        overlapping = env["hr.payslip"].search_count(
            [
                ("version_id", "=", version.id),
                ("date_from", "<=", period_end),
                ("date_to", ">=", period_start),
                ("state", "!=", "cancel"),
            ]
        )
        if not overlapping:
            return version
    return versions[:1]


def _prepare_version(version):
    write_vals = {
        "retencion_fuente": "procedimiento2",
        "withholding_percentage_id": False,
        "contract_date_start": date(2025, 7, 1),
    }
    for salary_field in ("contract_wage", "wage"):
        if salary_field in version._fields:
            write_vals[salary_field] = 20000000.0
    version.write(write_vals)


def _ensure_vacation_allocation(version, reference_date):
    allocation = env["hr.leave.allocation"].search(
        [
            ("employee_id", "=", version.employee_id.id),
            ("contract_id", "=", version.id),
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
            "name": f"Vacaciones {version.employee_id.name}",
            "holiday_status_id": leave_type.id,
            "employee_id": version.employee_id.id,
            "contract_id": version.id,
            "allocation_type": "accrual",
            "date_from": version._l10n_co_payroll_get_start_date() or reference_date,
            "number_of_days": 15.0,
            "state": "confirm",
            "nextcall": version._l10n_co_payroll_get_vacation_nextcall(reference_date),
        }
    )
    allocation._action_validate()
    return allocation


def _create_validated_payslip(version, target_date):
    struct = _get_struct(version)
    period_start, period_end = _month_period(target_date)
    payslip = env["hr.payslip"].create(
        {
            "name": f"TMP RTF {version.employee_id.name} {period_start:%Y-%m}",
            "employee_id": version.employee_id.id,
            "version_id": version.id,
            "company_id": version.company_id.id,
            "struct_id": struct.id,
            "date_from": period_start,
            "date_to": period_end,
            "liquidar_por": "nomina",
        }
    )
    payslip._onchange_employee()
    payslip.compute_sheet()
    payslip.write({"state": "validated"})
    base_line = payslip.line_ids.filtered(lambda line: line.code == "BAS_GRA_RTF")[:1]
    if not base_line or base_line.total <= 0:
        raise AssertionError(
            f"Missing positive BAS_GRA_RTF for payslip {payslip.id} ({period_start:%Y-%m})"
        )
    print(
        "PAYSPLIP_OK",
        payslip.id,
        period_start,
        period_end,
        round(base_line.total, 2),
        round(sum(payslip.line_ids.filtered(lambda line: line.code == "NET").mapped("total")), 2),
    )
    return payslip


def _assert_withholding_record(label, version, expected_from, expected_to):
    withholding = env["historical.withholdings"].search(
        [
            ("contract_id", "=", version.id),
            ("period_from", "=", expected_from),
            ("period_to", "=", expected_to),
        ],
        limit=1,
    )
    if not withholding:
        raise AssertionError(f"{label} missing withholding record {expected_from}/{expected_to}")
    if withholding.percentage_value <= 0:
        raise AssertionError(f"{label} expected positive percentage, got {withholding.percentage_value}")
    print(
        f"{label}_OK",
        f"version={version.id}",
        f"withholding={withholding.id}",
        f"percentage={withholding.percentage_value}",
        f"period={withholding.period_from}/{withholding.period_to}",
    )
    return withholding


def _validate_onchange_year(version):
    record = env["historical.withholdings"].create(
        {
            "percentage_value": 10.0,
            "contract_id": version.id,
        }
    )
    record.onchange_percentage_value(date(2025, 7, 10))
    if record.period_from != date(2025, 7, 1) or record.period_to != date(2025, 12, 31):
        raise AssertionError(
            f"onchange year mismatch: {record.period_from}/{record.period_to}"
        )
    print("ONCHANGE_YEAR_OK", record.period_from, record.period_to, record.percentage_update_date)


def _validate_january_and_july_cron(version):
    _ensure_vacation_allocation(version, date(2025, 7, 1))
    for month in range(7, 13):
        _create_validated_payslip(version, date(2025, month, 1))

    env["hr.version"].cron_calcular_porcentaje_retencion(
        day=JANUARY_REFERENCE.day,
        month=JANUARY_REFERENCE.month,
        year=JANUARY_REFERENCE.year,
    )
    january = _assert_withholding_record("WITHHOLDING_JAN", version, date(2026, 1, 1), date(2026, 6, 30))
    version.invalidate_recordset(["withholding_percentage_id"])
    if version.withholding_percentage_id.id != january.id:
        raise AssertionError("January cron did not assign withholding_percentage_id")

    for month in range(1, 7):
        _create_validated_payslip(version, date(2026, month, 1))

    env["hr.version"].cron_calcular_porcentaje_retencion(
        day=JULY_REFERENCE.day,
        month=JULY_REFERENCE.month,
        year=JULY_REFERENCE.year,
    )
    july = _assert_withholding_record("WITHHOLDING_JUL", version, date(2026, 7, 1), date(2026, 12, 31))
    version.invalidate_recordset(["withholding_percentage_id"])
    if version.withholding_percentage_id.id != july.id:
        raise AssertionError("July cron did not assign latest withholding_percentage_id")


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
        _ensure_validation_trace_variable(date(2025, 6, 30))
        _ensure_validation_trace_variable(date(2026, 6, 30))

        version = _find_candidate_version()
        print(
            "WITHHOLDING_CONTEXT",
            f"version={getattr(version, 'id', False)}",
            f"employee={getattr(getattr(version, 'employee_id', False), 'name', False)}",
            f"company={getattr(getattr(version, 'company_id', False), 'name', False)}",
            f"start={getattr(version, 'contract_date_start', False)}",
            f"retencion={getattr(version, 'retencion_fuente', False)}",
        )
        if not version:
            print("WITHHOLDING_ERROR missing candidate version")
            cr.rollback()
            return

        try:
            with cr.savepoint():
                _prepare_version(version)
                _validate_onchange_year(version)
                _validate_january_and_july_cron(version)
                raise _RollbackTest
        except _RollbackTest:
            pass
        finally:
            cr.rollback()


if __name__ == "__main__":
    main()
