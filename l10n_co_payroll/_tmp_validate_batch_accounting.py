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


def _month_period(reference_date):
    last_day = calendar.monthrange(reference_date.year, reference_date.month)[1]
    return reference_date.replace(day=1), reference_date.replace(day=last_day)


def _previous_month_period(reference_date):
    month = reference_date.month - 1 or 12
    year = reference_date.year - 1 if reference_date.month == 1 else reference_date.year
    base = reference_date.replace(year=year, month=month)
    return _month_period(base)


def _get_struct(contract):
    return (
        contract.structure_id
        or contract.structure_type_id.default_struct_id
        or env["hr.payroll.structure"].search(
            [("company_id", "in", [False, contract.company_id.id])],
            limit=1,
        )
    )


def _pick_account(*account_types):
    account = env["account.account"].search([("name", "ilike", "Salary Payable")], limit=1)
    if account:
        return account
    return env["account.account"].search([("account_type", "in", list(account_types))], limit=1)


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


def _prepare_accounting_config(contract, struct):
    payment_journal = env["account.journal"].search(
        [
            ("company_id", "=", contract.company_id.id),
            ("type", "=", "bank"),
            ("default_account_id", "!=", False),
        ],
        limit=1,
    )
    if not payment_journal:
        raise RuntimeError("Missing bank journal with default account for validation")

    employee_counterpart = _pick_account("liability_current", "asset_receivable", "liability_payable")
    third_counterpart = _pick_account("liability_current", "liability_payable", "asset_receivable")
    if not employee_counterpart or not third_counterpart:
        raise RuntimeError("Missing counterpart accounts for validation")

    struct.write(
        {
            "journal_payment_id": payment_journal.id,
            "journal_third_payment_id": payment_journal.id,
            "account_receivable_employee_id": employee_counterpart.id,
        }
    )

    area = contract.area_trabajo or "administracion"
    salary_rule_account_model = env["salary.rule.account"]
    rules = env["hr.salary.rule"].search(
        [
            ("company_id", "=", contract.company_id.id),
            "|",
            ("code", "=", "NET"),
            "&",
            ("origin_partner", "!=", False),
            ("origin_partner", "!=", "employee"),
        ]
    )
    for rule in rules:
        if salary_rule_account_model.search_count(
            [
                ("company_id", "=", contract.company_id.id),
                ("regla_salarial", "=", rule.id),
                ("area_trabajo", "=", area),
            ]
        ):
            continue
        account = third_counterpart if rule.origin_partner and rule.origin_partner != "employee" else employee_counterpart
        salary_rule_account_model.create(
            {
                "company_id": contract.company_id.id,
                "regla_salarial": rule.id,
                "area_trabajo": area,
                "account_debit": account.id,
                "account_credit": account.id,
            }
        )


def _ensure_partner(name):
    partner = env["res.partner"].search([("name", "=", name)], limit=1)
    if partner:
        return partner
    return env["res.partner"].create({"name": name, "company_type": "company"})


def _ensure_affiliations(company, employees):
    partners = {
        "eps": _ensure_partner("TMP EPS"),
        "fp": _ensure_partner("TMP AFP"),
        "fc": _ensure_partner("TMP FC"),
        "ccf": _ensure_partner("TMP CCF"),
        "arl": _ensure_partner("TMP ARL"),
        "icbf": _ensure_partner("TMP ICBF"),
        "sena": _ensure_partner("TMP SENA"),
        "dian": _ensure_partner("TMP DIAN"),
    }
    company.write(
        {
            "ccf_id": partners["ccf"].id,
            "arl_id": partners["arl"].id,
            "icbf_id": partners["icbf"].id,
            "sena_id": partners["sena"].id,
            "dian_id": partners["dian"].id,
        }
    )
    for employee in employees:
        employee.write(
            {
                "eps_id": partners["eps"].id,
                "fp_id": partners["fp"].id,
                "fc_id": partners["fc"].id,
                "ccf_id": partners["ccf"].id,
                "nivel_arl": employee.nivel_arl or "1",
            }
        )
    return partners


def _pick_contracts(period_start, period_end, count=2):
    versions = env["hr.version"].search(
        [
            ("employee_id", "!=", False),
            ("tipo_salario", "in", ("tradicional", "integral")),
            ("contract_date_start", "!=", False),
            ("contract_date_start", "<=", period_end),
            "|",
            ("contract_date_end", "=", False),
            ("contract_date_end", ">=", period_start),
        ],
        order="contract_date_start, id",
    )
    picked = env["hr.version"]
    for version in versions:
        if not version._l10n_co_payroll_is_active_contract():
            continue
        overlap = env["hr.payslip"].search_count(
            [
                ("version_id", "=", version.id),
                ("date_from", "<=", period_end),
                ("date_to", ">=", period_start),
                ("state", "!=", "cancel"),
            ]
        )
        if overlap:
            continue
        picked |= version
        if len(picked) >= count:
            break
    return picked


def _describe_move(move):
    if not move:
        return None
    return {
        "id": move.id,
        "state": move.state,
        "lines": len(move.line_ids),
        "partners": sorted(set(move.line_ids.mapped("partner_id").ids)),
    }


def _validate_scenario(batch_flag):
    today = fields.Date.context_today(env.user)
    period_start, period_end = _previous_month_period(today)
    _ensure_validation_trace_variable(period_end)
    contracts = _pick_contracts(period_start, period_end, 2)
    if len(contracts) < 2:
        raise RuntimeError("Not enough contracts for batch validation")

    company = contracts[0].company_id
    company.batch_payroll_move_lines = batch_flag
    _ensure_affiliations(company, contracts.mapped("employee_id"))

    structs = contracts.mapped(_get_struct)
    for contract in contracts:
        _ensure_vacation_allocation(contract, period_end)
        _prepare_accounting_config(contract, _get_struct(contract))

    run = env["hr.payslip.run"].create(
        {
            "name": f"TMP BATCH {'GROUP' if batch_flag else 'SPLIT'} {period_start.strftime('%Y-%m')}",
            "company_id": company.id,
            "date_start": period_start,
            "date_end": period_end,
            "liquidar_por": "nomina",
            "structure_id": structs[:1].id,
        }
    )
    run.generate_payslips(version_ids=contracts.ids)
    run.action_validate()

    main_move_ids = sorted(set(run.slip_ids.mapped("move_id").ids))
    payment_move_ids = sorted(set(run.slip_ids.mapped("move_id_pago").ids))
    third_move_ids = sorted(set(run.slip_ids.mapped("third_move_id").ids))

    expected_move_count = 1 if batch_flag else len(run.slip_ids)
    if len(main_move_ids) != expected_move_count:
        raise RuntimeError(
            f"Unexpected main move count for batch={batch_flag}: {main_move_ids} (expected {expected_move_count})"
        )
    if len(payment_move_ids) != expected_move_count:
        raise RuntimeError(
            f"Unexpected payment move count for batch={batch_flag}: {payment_move_ids} (expected {expected_move_count})"
        )
    if len(third_move_ids) != len(run.slip_ids):
        raise RuntimeError(
            f"Unexpected third move count for batch={batch_flag}: {third_move_ids} (expected {len(run.slip_ids)})"
        )
    if batch_flag and run.move_id.id not in main_move_ids:
        raise RuntimeError(f"Run move not synchronized for grouped batch: {run.move_id.id} not in {main_move_ids}")
    if not batch_flag and run.move_id:
        raise RuntimeError(f"Run move should stay empty for non-grouped batch, found {run.move_id.id}")

    print(
        "SCENARIO",
        batch_flag,
        "RUN",
        run.id,
        "main_moves",
        main_move_ids,
        "payment_moves",
        payment_move_ids,
        "third_moves",
        third_move_ids,
        "run_move",
        run.move_id.id or False,
    )
    for slip in run.slip_ids.sorted("id"):
        print(
            "SLIP",
            batch_flag,
            slip.id,
            slip.employee_id.name,
            slip.state,
            slip.move_id.id if slip.move_id else False,
            slip.move_id_pago.id if slip.move_id_pago else False,
            slip.third_move_id.id if slip.third_move_id else False,
            bool(slip.warning_message),
        )
        print("MOVE_MAIN", batch_flag, slip.id, _describe_move(slip.move_id))
        print("MOVE_PAY", batch_flag, slip.id, _describe_move(slip.move_id_pago))
        print("MOVE_THIRD", batch_flag, slip.id, _describe_move(slip.third_move_id))


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

        for batch_flag in (False, True):
            try:
                with env.cr.savepoint():
                    _validate_scenario(batch_flag)
                    raise _RollbackTest
            except _RollbackTest:
                cr.rollback()


if __name__ == "__main__":
    main()
