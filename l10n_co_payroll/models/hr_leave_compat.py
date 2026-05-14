from odoo import api, fields, models


class HrLeave(models.Model):
    _inherit = "hr.leave"

    payslip_input_id = fields.Many2one("hr.payslip.input", string="Entrada de nomina")
    remaining_addition = fields.Float(
        help="Almacena el valor adicionado desde el ultimo cumplemes del contrato hasta la fecha de la definitiva"
    )
    value_vacations = fields.Float(string="Valor", compute="_compute_l10n_co_payroll_value_vacations")
    contract_id = fields.Many2one(
        "hr.version",
        string="Contrato",
        help="Registro salarial al que pertenece la ausencia.",
    )
    number_of_days_calendar = fields.Float(
        string="Dias Calendario",
        compute="_compute_l10n_co_payroll_number_of_days_calendar",
        store=True,
        copy=False,
        help="Numero de dias calendario desde la fecha de inicio hasta la fecha de finalizacion.",
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

    @api.depends("date_from", "date_to")
    def _compute_l10n_co_payroll_number_of_days_calendar(self):
        for leave in self:
            if leave.date_from and leave.date_to:
                date_from = fields.Datetime.to_datetime(leave.date_from).date()
                date_to = fields.Datetime.to_datetime(leave.date_to).date()
                leave.number_of_days_calendar = (date_to - date_from).days + 1
            else:
                leave.number_of_days_calendar = 0

    @api.depends(
        "payslip_input_id.amount",
        "holiday_status_id.work_entry_type_id.code",
        "employee_id",
        "date_from",
        "date_to",
    )
    def _compute_l10n_co_payroll_value_vacations(self):
        for leave in self:
            value = 0.0
            if leave.payslip_input_id:
                value = leave.payslip_input_id.amount
            elif (
                leave.holiday_status_id.work_entry_type_id.code == "VAC"
                and leave.employee_id
                and leave.date_from
                and leave.date_to
            ):
                payslips = self.env["hr.payslip"].search(
                    [
                        ("employee_id", "=", leave.employee_id.id),
                        ("liquidar_por", "=", "vacaciones"),
                        ("state", "in", ("done", "validated", "paid")),
                        ("date_from", ">=", fields.Datetime.to_datetime(leave.date_from).date()),
                        ("date_to", "<=", fields.Datetime.to_datetime(leave.date_to).date()),
                    ]
                )
                for payslip in payslips:
                    value += sum(line.amount for line in payslip.line_ids.filtered(lambda line: line.code == "ING_SAL"))
            leave.value_vacations = value

    def _compute_l10n_co_payroll_contract_manager(self):
        has_group = self.env.user.has_group("hr_payroll.group_hr_payroll_manager")
        for leave in self:
            leave.contract_manager = has_group

    @api.onchange("employee_id")
    def _onchange_l10n_co_payroll_employee_id(self):
        if self.employee_id and (not self.contract_id or self.contract_id.employee_id != self.employee_id):
            self.contract_id = self.employee_id._l10n_co_payroll_get_active_contract()

