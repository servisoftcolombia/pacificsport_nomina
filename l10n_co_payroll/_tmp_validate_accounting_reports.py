import calendar
from datetime import date

import odoo
from dateutil.relativedelta import relativedelta
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
    return _month_period(reference_date - relativedelta(months=1))


def _get_struct(contract):
    return (
        contract.structure_id
        or contract.structure_type_id.default_struct_id
        or env["hr.payroll.structure"].search(
            [("company_id", "in", [False, contract.company_id.id])],
            limit=1,
        )
    )


def _get_active_contract(period_start, period_end):
    contracts = env["hr.version"].search(
        [
            ("employee_id", "!=", False),
            ("contract_date_start", "!=", False),
        ],
        order="id",
    )
    for contract in contracts:
        contract_start = contract._l10n_co_payroll_get_start_date() or contract.contract_date_start
        contract_end = contract._l10n_co_payroll_get_end_date()
        if contract_start and contract_start > period_end:
            continue
        if contract_end and contract_end < period_start:
            continue

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
            return contract
    return env["hr.version"]


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
    print(
        "AFFILIATIONS_TEMP",
        f"company={company.id}",
        f"employees={employees.ids}",
        f"partners={ {key: value.id for key, value in partners.items()} }",
    )
    return partners


def _ensure_employee_bank_account(contract):
    home_partner = contract.employee_id.address_home_id
    if not home_partner:
        home_partner = env["res.partner"].create(
            {
                "name": contract.employee_id.name,
                "company_type": "person",
                "email": contract.employee_id.work_email or f"tmp.employee.{contract.employee_id.id}@example.com",
                "fe_tipo_documento": "13",
                "fe_nit": str(100000000 + contract.employee_id.id),
            }
        )
        contract.employee_id.address_home_id = home_partner
        print(
            "HOME_PARTNER_TEMP",
            f"employee={contract.employee_id.id}",
            f"partner={home_partner.id}",
            f"document={home_partner.fe_tipo_documento}/{home_partner.fe_nit}",
        )

    bank = env["res.bank"].search([("bic", "!=", False)], limit=1)
    if not bank:
        bank = env["res.bank"].create({"name": "TMP Bank", "bic": "0123"})

    partner_bank = env["res.partner.bank"].search([("partner_id", "=", home_partner.id)], limit=1)
    values = {
        "partner_id": home_partner.id,
        "bank_id": bank.id,
        "acc_number": "00012345678901234",
        "tipo_cuenta": "ahorros",
    }
    if partner_bank:
        partner_bank.write(values)
    else:
        partner_bank = env["res.partner.bank"].create(values)
    contract.employee_id.bank_account_id = partner_bank
    print(
        "EMPLOYEE_BANK_TEMP",
        f"employee={contract.employee_id.id}",
        f"partner={home_partner.id}",
        f"bank_account={partner_bank.id}",
        f"tipo_cuenta={partner_bank.tipo_cuenta}",
        f"acc_number={partner_bank.acc_number}",
    )
    return partner_bank


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

    print(
        "ACCOUNTING_CONFIG",
        f"struct={struct.id}",
        f"payment_journal={payment_journal.id}",
        f"employee_counterpart={employee_counterpart.id}",
        f"third_counterpart={third_counterpart.id}",
        f"rule_accounts={len(rules)}",
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
    print("VACATION_ALLOCATION_TEMP", allocation.id, allocation.employee_id.id, allocation.contract_id.id)
    return allocation


def _create_payslip(contract, run, period_start, period_end):
    struct = _get_struct(contract)
    if not struct:
        raise RuntimeError(f"Missing payroll structure for contract {contract.id}")

    payslip = env["hr.payslip"].create(
        {
            "name": f"TMP accounting {contract.employee_id.name}",
            "employee_id": contract.employee_id.id,
            "version_id": contract.id,
            "company_id": contract.company_id.id,
            "struct_id": struct.id,
            "payslip_run_id": run.id,
            "date_from": period_start,
            "date_to": period_end,
            "liquidar_por": "nomina",
        }
    )
    payslip._onchange_employee()
    payslip.compute_sheet()
    return payslip


def _print_non_zero_lines(payslip):
    rows = []
    for line in payslip.line_ids.sorted(lambda row: (row.sequence, row.id)):
        amount = round(line.total, 2)
        if not amount:
            continue
        rows.append((line.code, amount, line.salary_rule_id.origin_partner or ""))
    print("LINES", payslip.id, rows)


def _print_move(label, move):
    if not move:
        print(f"{label}: NONE")
        return
    lines = move.line_ids.sorted(lambda row: (row.debit == 0, row.id))
    payload = [
        (
            line.name,
            round(line.debit, 2),
            round(line.credit, 2),
            line.partner_id.id or False,
            line.account_id.id,
        )
        for line in lines
    ]
    print(f"{label}: id={move.id} state={move.state} journal={move.journal_id.id} lines={payload}")


def _validate_reports(payslip, run):
    env.flush_all()
    env["bancos.report"].init()
    env.cr.execute(
        """
        select id, nombre_beneficiario, valor_transaccion, nombre_lote, tipo_de_cuenta
        from bancos_report
        where id = %s
        """,
        [payslip.id],
    )
    bank_rows = env.cr.fetchall()
    print(
        "REPORT_BANCOS",
        f"rows={len(bank_rows)}",
        bank_rows,
    )

    env["pila.report"].init()
    env.cr.execute(
        """
        select id, empleado, liquidar_por, dias_a_pagar, ibc_fp, valor_cotizacion_salud
        from pila_report
        where empleado = %s
        """,
        [payslip.employee_id.name],
    )
    pila_rows = env.cr.fetchall()
    print(
        "REPORT_PILA",
        f"rows={len(pila_rows)}",
        pila_rows,
    )

    report = env["bancolombia.report"].with_context(lote=run.id)
    report.init()
    env.cr.execute("select id, dato from bancolombia_report order by id limit 5")
    bancolombia_rows = env.cr.fetchall()
    print(
        "REPORT_BANCOLOMBIA",
        f"rows={len(bancolombia_rows)}",
        bancolombia_rows[:2],
    )


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
        period_start, period_end = _previous_month_period(today)
        contract = _get_active_contract(period_start, period_end)
        if not contract:
            print("ERROR missing active contract for validation period")
            return

        struct = _get_struct(contract)
        print(
            "VALIDATION_TARGET",
            f"contract={contract.id}",
            f"employee={contract.employee_id.name}",
            f"struct={getattr(struct, 'id', False)}",
            f"period={period_start}/{period_end}",
        )

        try:
            with env.cr.savepoint():
                _ensure_validation_trace_variable(period_end)
                _ensure_vacation_allocation(contract, period_end)
                _ensure_affiliations(contract.company_id, contract.employee_id)
                _ensure_employee_bank_account(contract)
                _prepare_accounting_config(contract, struct)
                run = env["hr.payslip.run"].create(
                    {
                        "name": f"TMP Accounting {period_start.strftime('%Y-%m')}",
                        "company_id": contract.company_id.id,
                        "date_start": period_start,
                        "date_end": period_end,
                        "liquidar_por": "nomina",
                    }
                )
                payslip = _create_payslip(contract, run, period_start, period_end)
                _print_non_zero_lines(payslip)
                payslip.action_validate()
                print(
                    "PAYSPLIP",
                    f"id={payslip.id}",
                    f"state={payslip.state}",
                    f"move_id={payslip.move_id.id or False}",
                    f"move_id_pago={payslip.move_id_pago.id or False}",
                    f"third_move_id={payslip.third_move_id.id or False}",
                    f"warning={payslip.warning_message or False}",
                )
                _print_move("MOVE_MAIN", payslip.move_id)
                _print_move("MOVE_PAYMENT", payslip.move_id_pago)
                _print_move("MOVE_THIRD", payslip.third_move_id)
                if not payslip.third_move_id:
                    try:
                        third_move_vals = payslip._l10n_co_payroll_prepare_third_payment_move_vals()
                        print("MOVE_THIRD_PREPARE", bool(third_move_vals), third_move_vals and len(third_move_vals.get("line_ids", [])))
                    except Exception as err:
                        print(f"MOVE_THIRD_ERROR {type(err).__name__}: {err}")
                _validate_reports(payslip, run)
                raise _RollbackTest
        except _RollbackTest:
            cr.rollback()
            return
        except Exception as err:
            print(f"ERROR {type(err).__name__}: {err}")
            cr.rollback()


if __name__ == "__main__":
    main()
