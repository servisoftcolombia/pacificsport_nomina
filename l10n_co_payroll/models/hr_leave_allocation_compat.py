from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class HrLeaveAllocation(models.Model):
    _inherit = "hr.leave.allocation"

    saldo = fields.Boolean(string="Es saldo", default=False)
    anticipated_vacations = fields.Float(
        string="Vacaciones anticipadas",
        help="Dias anticipados de vacaciones aun no devengadas.",
        default=0,
        tracking=True,
    )
    contract_id = fields.Many2one(
        "hr.version",
        string="Contrato",
        help="Registro salarial al que pertenece la asignacion.",
    )
    work_entry_type_code = fields.Char(
        string="Codigo tipo de ausencia",
        related="holiday_status_id.work_entry_type_id.code",
        help="Permite identificar el codigo del tipo de ausencia.",
    )
    contract_manager = fields.Boolean(
        string="Administrador de contratos",
        compute="_compute_l10n_co_payroll_contract_manager",
        help="Permite identificar si el usuario actual tiene permisos de administracion de nomina.",
    )

    def _compute_l10n_co_payroll_contract_manager(self):
        has_group = self.env.user.has_group("hr_payroll.group_hr_payroll_manager")
        for allocation in self:
            allocation.contract_manager = has_group

    @api.constrains("employee_id", "contract_id", "holiday_status_id", "state")
    def _check_l10n_co_payroll_unique_vacation_allocation(self):
        for allocation in self:
            if (
                allocation.holiday_status_id.work_entry_type_id.code != "VAC"
                or not allocation.employee_id
                or not allocation.contract_id
                or allocation.state in ("cancel", "refuse")
            ):
                continue
            duplicate = self.search(
                [
                    ("id", "!=", allocation.id),
                    ("employee_id", "=", allocation.employee_id.id),
                    ("contract_id", "=", allocation.contract_id.id),
                    ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
                    ("state", "not in", ("cancel", "refuse")),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError("El empleado solo puede tener una asignacion de vacaciones activa por contrato.")

    @api.onchange("employee_id")
    def _onchange_l10n_co_payroll_employee_id(self):
        if self.employee_id and (not self.contract_id or self.contract_id.employee_id != self.employee_id):
            self.contract_id = self.employee_id._l10n_co_payroll_get_active_contract()

    @api.onchange("holiday_status_id")
    def _onchange_l10n_co_payroll_holiday_status_id(self):
        if self.holiday_status_id.work_entry_type_id.code == "VAC":
            self.name = "Vacaciones"
            if "allocation_type" in self._fields:
                self.allocation_type = "accrual"
            self.number_of_days = self.number_of_days or 0
            if self.contract_id:
                contract_start = (
                    self.contract_id._l10n_co_payroll_get_start_date()
                    if hasattr(self.contract_id, "_l10n_co_payroll_get_start_date")
                    else False
                )
                if contract_start:
                    self.date_from = datetime.combine(contract_start, time(5, 0, 0))
        else:
            self.anticipated_vacations = 0
            if self.contract_id:
                self.date_from = False

    @api.onchange("contract_id")
    def _onchange_l10n_co_payroll_contract_id(self):
        if self.contract_id and self.holiday_status_id.work_entry_type_id.code == "VAC":
            self._onchange_l10n_co_payroll_holiday_status_id()

    @api.onchange("anticipated_vacations")
    def _onchange_l10n_co_payroll_anticipated_vacations(self):
        if not self.employee_id:
            return
        company = self.employee_id.company_id
        limit = company.anticipated_vacation_limit
        if limit and self.anticipated_vacations > limit:
            raise UserError(
                f"Se supera el limite de dias de vacaciones anticipadas establecido por la compania en {limit} dias."
            )

    def _sum_balance_allocation(self, values):
        employee = self.env["hr.employee"].browse(values.get("employee_id"))

        if not employee.exists():
            raise UserError("Empleado no existe.")

        contract = (
            self.env["hr.version"].browse(values.get("contract_id"))
            if values.get("contract_id")
            else employee._l10n_co_payroll_get_active_contract()
        )
        if not contract:
            raise UserError(f"El empleado {employee.name}(id={employee.id}) no cuenta con un contrato activo.")

        allocation = self.search(
            [
                ("employee_id", "=", employee.id),
                ("contract_id", "=", contract.id),
                ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
                ("state", "not in", ("cancel", "refuse")),
            ],
            limit=1,
        )
        if not allocation:
            raise UserError(f"Empleado {employee.name}(id={employee.id}) sin asignacion de vacaciones activa.")

        days = values.get("number_of_days", 0)
        allocation.message_post(body=f"Asignados {days} dias por concepto de saldo de vacaciones.")
        allocation.number_of_days += days
        return allocation

    def _l10n_co_payroll_is_vacation_accrual(self):
        self.ensure_one()
        return bool(
            self.contract_id
            and self.employee_id
            and self.allocation_type == "accrual"
            and not self.accrual_plan_id
            and self.holiday_status_id.work_entry_type_id.code == "VAC"
        )

    def _l10n_co_payroll_get_vacation_nextcall(self, reference_date=None):
        self.ensure_one()
        if not self.contract_id or not hasattr(self.contract_id, "_l10n_co_payroll_get_vacation_nextcall"):
            return False
        return self.contract_id._l10n_co_payroll_get_vacation_nextcall(reference_date)

    def _l10n_co_payroll_get_unpaid_leave_days(self, period_start, period_end):
        self.ensure_one()
        employee = self.employee_id
        if not employee:
            return 0.0
        leave_data = employee._get_leave_days_data_batch(
            datetime.combine(period_start, time.min),
            datetime.combine(period_end, time.min),
            domain=[
                ("holiday_id.contract_id", "=", self.contract_id.id),
                ("holiday_id.holiday_status_id.unpaid", "=", True),
                ("time_type", "=", "leave"),
            ],
        )
        return (leave_data.get(employee.id) or {}).get("days", 0.0) or 0.0

    def _l10n_co_payroll_get_vacation_days_to_accrue(self, period_start, period_end):
        self.ensure_one()
        contract = self.contract_id
        if not contract or not contract._l10n_co_payroll_supports_social_benefits():
            return 0.0
        unpaid_days = self._l10n_co_payroll_get_unpaid_leave_days(period_start, period_end)
        worked_days = max(0.0, 30.0 - unpaid_days)
        return round((worked_days * 1.25) / 30.0, 2)

    def _l10n_co_payroll_apply_vacation_accrual(self, today):
        self.ensure_one()
        if not self._l10n_co_payroll_is_vacation_accrual():
            return

        contract = self.contract_id
        if not contract._l10n_co_payroll_supports_social_benefits():
            return

        nextcall = self.nextcall or self._l10n_co_payroll_get_vacation_nextcall(today)
        if not nextcall:
            return
        nextcall = fields.Date.to_date(nextcall)

        while nextcall and nextcall <= today:
            period_start = nextcall - relativedelta(months=1)
            accrued_days = self._l10n_co_payroll_get_vacation_days_to_accrue(period_start, nextcall)
            values = {
                "nextcall": nextcall + relativedelta(months=1),
            }

            anticipated_vacations = self.anticipated_vacations
            if anticipated_vacations > 0 and accrued_days > 0:
                recovered_days = min(anticipated_vacations, accrued_days)
                values["anticipated_vacations"] = anticipated_vacations - recovered_days
                accrued_days -= recovered_days

            if accrued_days > 0:
                values["number_of_days"] = self.number_of_days + accrued_days

            super(HrLeaveAllocation, self.with_context(anticipated_vacations=True)).write(values)
            nextcall = fields.Date.to_date(self.nextcall)

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        for values in vals_list:
            values = dict(values)
            if values.get("employee_id") and not values.get("contract_id"):
                contract = self.env["hr.employee"].browse(values["employee_id"])._l10n_co_payroll_get_active_contract()
                if contract:
                    values["contract_id"] = contract.id
            if values.get("contract_id") and values.get("holiday_status_id"):
                contract = self.env["hr.version"].browse(values["contract_id"])
                leave_type = self.env["hr.leave.type"].browse(values["holiday_status_id"])
                if (
                    contract
                    and leave_type.work_entry_type_id.code == "VAC"
                    and not values.get("accrual_plan_id")
                    and not values.get("nextcall")
                ):
                    nextcall = contract._l10n_co_payroll_get_vacation_nextcall(fields.Date.context_today(self))
                    if nextcall:
                        values["nextcall"] = nextcall
            if values.get("saldo"):
                records |= self._sum_balance_allocation(values)
                continue
            records |= super(HrLeaveAllocation, self).create([values])
        return records

    def write(self, vals):
        vals = dict(vals)
        if "anticipated_vacations" in vals and not self.env.context.get("anticipated_vacations", False):
            for allocation in self:
                delta = vals["anticipated_vacations"] - allocation.anticipated_vacations
                super(HrLeaveAllocation, allocation.with_context(anticipated_vacations=True)).write(
                    {"number_of_days": allocation.number_of_days + delta}
                )
        return super().write(vals)

    def remaining_days(self):
        result = {}
        for allocation in self:
            contract = allocation.contract_id or allocation.employee_id._l10n_co_payroll_get_active_contract()
            if not allocation.employee_id or not contract:
                result[allocation.employee_id.id] = 0.0
                continue

            leave_domain = [
                ("employee_id", "=", allocation.employee_id.id),
                ("contract_id", "=", contract.id),
                ("state", "=", "validate"),
                ("holiday_status_id", "=", allocation.holiday_status_id.id),
            ]
            allocations = allocation.env["hr.leave.allocation"].search(leave_domain)
            requests = allocation.env["hr.leave"].search(leave_domain)
            result[allocation.employee_id.id] = sum(allocations.mapped("number_of_days")) - sum(
                requests.mapped("number_of_days")
            )
        return result

    @api.model
    def _update_accrual(self):
        result = super()._update_accrual()
        today = fields.Date.context_today(self)
        allocations = self.search(
            [
                ("allocation_type", "=", "accrual"),
                ("accrual_plan_id", "=", False),
                ("employee_id.active", "=", True),
                ("state", "=", "validate"),
                ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
                ("contract_id", "!=", False),
                "|",
                ("date_to", "=", False),
                ("date_to", ">", fields.Datetime.now()),
                "|",
                ("nextcall", "=", False),
                ("nextcall", "<=", today),
            ]
        )
        for allocation in allocations:
            allocation._l10n_co_payroll_apply_vacation_accrual(today)
        return result
