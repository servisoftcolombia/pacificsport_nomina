from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    today = fields.Date.context_today(env.user)
    allocations = env["hr.leave.allocation"].search(
        [
            ("allocation_type", "=", "accrual"),
            ("accrual_plan_id", "=", False),
            ("state", "not in", ("cancel", "refuse")),
            ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
            ("contract_id", "!=", False),
        ]
    )
    for allocation in allocations:
        contract = allocation.contract_id
        if not contract or not hasattr(contract, "_l10n_co_payroll_get_vacation_nextcall"):
            continue
        nextcall = contract._l10n_co_payroll_get_vacation_nextcall(today)
        values = {}
        if nextcall and (not allocation.nextcall or allocation.nextcall <= today):
            values["nextcall"] = nextcall
        if not allocation.date_from and hasattr(contract, "_l10n_co_payroll_get_start_date"):
            values["date_from"] = contract._l10n_co_payroll_get_start_date()
        if values:
            allocation.write(values)
