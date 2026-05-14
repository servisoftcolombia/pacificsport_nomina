import calendar
from datetime import date, timedelta

import odoo
from dateutil.relativedelta import relativedelta
from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import ValidationError
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
    }
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


def _get_vacation_compensation_contract(reference_date):
    threshold = reference_date - relativedelta(months=9)
    allocations = env["hr.leave.allocation"].search(
        [
            ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
            ("state", "=", "validate"),
            ("contract_id", "!=", False),
        ],
        order="date_from, id",
    )
    for allocation in allocations:
        contract = allocation.contract_id
        contract_start = contract._l10n_co_payroll_get_start_date()
        contract_end = contract._l10n_co_payroll_get_end_date()
        if not contract_start or contract_start > threshold:
            continue
        if contract_end and contract_end < reference_date:
            continue
        return contract
    return env["hr.version"]


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


def _create_payslip(contract, liquidation, date_from, date_to, extra_vals=None, state="draft"):
    struct = _get_struct(contract)
    if not struct:
        raise RuntimeError(f"Missing payroll structure for contract {contract.id}")

    vals = {
        "name": f"TMP {liquidation} {contract.employee_id.name}",
        "employee_id": contract.employee_id.id,
        "version_id": contract.id,
        "company_id": contract.company_id.id,
        "struct_id": struct.id,
        "date_from": date_from,
        "date_to": date_to,
        "liquidar_por": liquidation,
    }
    if extra_vals:
        vals.update(extra_vals)

    payslip = env["hr.payslip"].create(vals)
    payslip._onchange_employee()
    payslip.compute_sheet()
    if state != "draft":
        payslip.write({"state": state})
    return payslip


def _print_result(label, payslip):
    net = sum(payslip.line_ids.filtered(lambda line: line.code == "NET").mapped("total"))
    print(
        f"{label}: OK employee={payslip.employee_id.id} contract={payslip.contract_id.id} "
        f"state={payslip.state} liquidation={payslip.liquidar_por} lines={len(payslip.line_ids)} "
        f"worked_days={len(payslip.worked_days_line_ids)} net={round(net, 2)} "
        f"date_from_prima={payslip.date_from_prima} date_from_ces={payslip.date_from_cesantias} "
        f"dias_prima={round(payslip.dias_prima or 0, 2)} "
        f"dias_ces={round(payslip.dias_cesantias or 0, 2)} "
        f"dias_int_ces={round(payslip.dias_intereses_cesantias or 0, 2)}"
    )


def _semester_start(target_date):
    return date(target_date.year, 7 if target_date.month >= 7 else 1, 1)


def _get_free_month_period(contract, reference_date, months_back=12):
    for offset in range(0, months_back + 1):
        target = reference_date - relativedelta(months=offset)
        period_start, period_end = _current_month_period(target)
        overlapping = env["hr.payslip"].search_count(
            [
                ("employee_id", "=", contract.employee_id.id),
                ("contract_id", "=", contract.id),
                ("date_from", "<=", period_end),
                ("date_to", ">=", period_start),
                ("state", "!=", "cancel"),
            ]
        )
        if not overlapping:
            return period_start, period_end
    return _current_month_period(reference_date)


def _year_start(contract, target_date):
    if contract.fecha_corte:
        return max(date(contract.fecha_corte.year, 1, 1), contract._l10n_co_payroll_get_start_date() or target_date)
    return max(date(target_date.year, 1, 1), contract._l10n_co_payroll_get_start_date() or target_date)


def _validate_prima(active_contract, today):
    period_start, period_end = _current_month_period(today)
    with env.cr.savepoint():
        _ensure_vacation_allocation(active_contract, period_end)
        payslip = _create_payslip(active_contract, "prima", period_start, period_end)
        _print_result("prima", payslip)
        raise _RollbackTest


def _validate_definitive_after_partial_benefits(contract):
    contract_end = contract._l10n_co_payroll_get_end_date()
    if not contract_end:
        print(f"definitiva_partial: ERROR contract={contract.id} missing contract end date")
        return

    definitive_start = contract_end.replace(day=1)
    partial_end = definitive_start - timedelta(days=1)
    prima_start = max(_semester_start(contract_end), contract._l10n_co_payroll_get_start_date() or definitive_start)
    ces_start = _year_start(contract, contract_end)

    if partial_end < prima_start or partial_end < ces_start:
        print(
            f"definitiva_partial: SKIP contract={contract.id} "
            f"prima_start={prima_start} ces_start={ces_start} partial_end={partial_end}"
        )
        return

    expected_from_prima = partial_end + timedelta(days=1)
    expected_from_ces = partial_end + timedelta(days=1)

    with env.cr.savepoint():
        _ensure_vacation_allocation(contract, contract_end)
        prima = _create_payslip(contract, "prima", prima_start, partial_end, state="validated")
        ces = _create_payslip(contract, "cesantias", ces_start, partial_end, state="validated")
        definitiva = _create_payslip(contract, "definitiva", definitive_start, contract_end)

        mismatch = []
        if definitiva.date_from_prima != expected_from_prima:
            mismatch.append(f"date_from_prima={definitiva.date_from_prima} expected={expected_from_prima}")
        if definitiva.date_from_cesantias != expected_from_ces:
            mismatch.append(f"date_from_cesantias={definitiva.date_from_cesantias} expected={expected_from_ces}")
        if definitiva.dias_prima <= 0:
            mismatch.append(f"dias_prima={definitiva.dias_prima}")
        if definitiva.dias_intereses_cesantias <= 0:
            mismatch.append(f"dias_intereses_cesantias={definitiva.dias_intereses_cesantias}")

        if mismatch:
            print(
                "definitiva_partial: ERROR "
                f"contract={contract.id} prima_id={prima.id} ces_id={ces.id} definitiva_id={definitiva.id} "
                + " | ".join(mismatch)
            )
        else:
            _print_result("definitiva_partial", definitiva)
        raise _RollbackTest


def _validate_vacation_compensation(contract, today):
    period_start, period_end = _get_free_month_period(contract, today)
    with env.cr.savepoint():
        _ensure_vacation_allocation(contract, period_end)
        payslip = env["hr.payslip"].create(
            {
                "name": f"TMP comp {contract.employee_id.name}",
                "employee_id": contract.employee_id.id,
                "version_id": contract.id,
                "company_id": contract.company_id.id,
                "struct_id": _get_struct(contract).id,
                "date_from": period_start,
                "date_to": period_end,
                "liquidar_por": "nomina",
                "dias_vacaciones_compensadas": 5,
            }
        )
        payslip._onchange_employee()
        payslip._onchange_liquidar_por()
        payslip.compute_sheet()
        vac_input = payslip.input_line_ids.filtered(lambda line: line.input_type_id.code == "VACACIONES_COMPENSADAS")
        if not vac_input:
            print(
                "vac_comp_nomina: ERROR "
                f"employee={contract.employee_id.id} contract={contract.id} missing VACACIONES_COMPENSADAS input"
            )
        else:
            print(
                "vac_comp_nomina: OK "
                f"employee={contract.employee_id.id} contract={contract.id} "
                f"period={period_start}/{period_end} "
                f"inputs={[(line.input_type_id.code, round(line.amount, 2), line.descripcion) for line in vac_input]}"
            )
        raise _RollbackTest


def _validate_vacation_compensation_limit(contract, today):
    period_start, period_end = _get_free_month_period(contract, today)
    with env.cr.savepoint():
        _ensure_vacation_allocation(contract, period_end)
        payslip = env["hr.payslip"].new(
            {
                "employee_id": contract.employee_id.id,
                "version_id": contract.id,
                "company_id": contract.company_id.id,
                "struct_id": _get_struct(contract).id,
                "date_from": period_start,
                "date_to": period_end,
                "liquidar_por": "nomina",
                "dias_vacaciones_compensadas": 8,
            }
        )
        payslip._onchange_employee()
        try:
            payslip._onchange_liquidar_por()
        except ValidationError as err:
            print(f"vac_comp_limit: OK {err}")
            raise _RollbackTest
        print("vac_comp_limit: ERROR expected ValidationError for dias_vacaciones_compensadas=8")
        raise _RollbackTest


def _validate_definitive_vacation_compensation(contract):
    contract_end = contract._l10n_co_payroll_get_end_date()
    if not contract_end:
        print(f"definitiva_vac_comp: ERROR contract={contract.id} missing contract end date")
        return

    with env.cr.savepoint():
        _ensure_vacation_allocation(contract, contract_end)
        definitive_start = contract_end.replace(day=1)
        payslip = _create_payslip(contract, "definitiva", definitive_start, contract_end)
        vac_inputs = payslip.input_line_ids.filtered(lambda line: line.input_type_id.code in ("VACACIONES_COMPENSADAS", "VACACIONES_ANTICIPADAS"))
        print(
            "definitiva_vac_comp: OK "
            f"employee={contract.employee_id.id} contract={contract.id} "
            f"dias_vac_comp={round(payslip.dias_vacaciones_compensadas or 0, 2)} "
            f"inputs={[(line.input_type_id.code, round(line.amount, 2), line.descripcion) for line in vac_inputs]}"
        )
        raise _RollbackTest


def _get_payment_validation_journal():
    journal = env["account.journal"].search(
        [
            ("type", "in", ("bank", "cash", "general")),
            ("default_account_id", "!=", False),
        ],
        limit=1,
    )
    if not journal:
        raise RuntimeError("No payment journal with default account found")
    account = journal.default_account_id
    journal.write(
        {
            "journal_payroll": True,
            "severance_account_id": account.id,
            "severance_interest_account_id": account.id,
            "service_bonus_account_id": account.id,
            "vacations_account_id": account.id,
        }
    )
    return journal, account


def _validate_payment_move(contract, liquidation, date_from, date_to, extra_vals=None):
    with env.cr.savepoint():
        if liquidation in ("nomina", "vacaciones", "definitiva"):
            _ensure_vacation_allocation(contract, date_to)
        journal, account = _get_payment_validation_journal()
        struct = _get_struct(contract)
        struct.write(
            {
                "journal_payment_id": journal.id,
                "account_receivable_employee_id": account.id,
            }
        )
        payslip = _create_payslip(contract, liquidation, date_from, date_to, extra_vals=extra_vals, state="validated")
        payslip._l10n_co_payroll_create_payment_moves()
        move = payslip.move_id_pago
        if not move:
            print(f"payment_{liquidation}: ERROR contract={contract.id} no payment move created")
            raise _RollbackTest

        labels = [line.name for line in move.line_ids]
        payslip_codes = [(line.code, round(line.total, 2)) for line in payslip.line_ids]
        print(
            f"payment_{liquidation}: OK contract={contract.id} move={move.id} "
            f"lines={len(move.line_ids)} amount_total={round(sum(move.line_ids.mapped('balance')), 2)} "
            f"labels={labels} payslip_codes={payslip_codes}"
        )
        raise _RollbackTest


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
        _ensure_validation_trace_variable(today - relativedelta(years=1))
        _ensure_validation_trace_variable(today)

        active_contract = _get_active_contract(today)
        definitive_contract = _get_definitive_contract(today)
        compensation_contract = _get_vacation_compensation_contract(today)

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
        print(
            "COMPENSATION_CONTRACT",
            getattr(compensation_contract, "id", False),
            getattr(getattr(compensation_contract, "employee_id", False), "name", False),
            getattr(compensation_contract, "state", False),
        )

        if active_contract:
            try:
                _validate_prima(active_contract, today)
            except _RollbackTest:
                pass
            try:
                period_start, period_end = _current_month_period(today)
                _validate_payment_move(active_contract, "prima", period_start, period_end)
            except _RollbackTest:
                pass
            try:
                period_start, period_end = _current_month_period(today)
                _validate_payment_move(active_contract, "cesantias", period_start, period_end)
            except _RollbackTest:
                pass
        if compensation_contract:
            try:
                _validate_vacation_compensation(compensation_contract, today)
            except _RollbackTest:
                pass
            try:
                _validate_vacation_compensation_limit(compensation_contract, today)
            except _RollbackTest:
                pass

        if definitive_contract:
            try:
                _validate_definitive_after_partial_benefits(definitive_contract)
            except _RollbackTest:
                pass
            try:
                _validate_definitive_vacation_compensation(definitive_contract)
            except _RollbackTest:
                pass
            try:
                contract_end = definitive_contract._l10n_co_payroll_get_end_date()
                _validate_payment_move(definitive_contract, "definitiva", contract_end.replace(day=1), contract_end)
            except _RollbackTest:
                pass

        cr.rollback()


if __name__ == "__main__":
    main()
