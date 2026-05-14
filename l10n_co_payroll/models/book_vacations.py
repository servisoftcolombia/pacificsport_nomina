from odoo import api, fields, models


class BookVacations(models.Model):
    _name = "book.vacations"
    _description = "Vacation Book"
    _rec_name = "employee_id"

    name = fields.Char(string="Título del informe", compute="_compute_name", default="LIBRO DE VACACIONES")
    contract_id = fields.Many2one("hr.version", string="Contrato", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Nombre del empleado", related="contract_id.employee_id")
    document_type = fields.Char(string="Tipo de documento", related="employee_id.address_home_id.fe_tipo_documento")
    employee_identification = fields.Char(string="Número de documento", related="employee_id.address_home_id.fe_nit")
    company_id = fields.Many2one("res.company", string="Nombre de la empresa", related="employee_id.company_id")
    nit = fields.Char(string="Nit de la empresa", related="company_id.partner_id.fe_nit")
    date_to = fields.Date(string="Fecha de corte", compute="_compute_date_to", readonly=True)
    date_start_contract = fields.Date(string="Fecha de ingreso", compute="_compute_date_start_contract", readonly=True)

    accrued_vacations = fields.Float(string="Días acumulados", compute="_compute_vacations")
    vacations_taken = fields.Float(string="Días disfrutados", compute="_compute_vacations")
    compensated_vacations = fields.Float(string="Días compensados", compute="_compute_vacations")
    remaining_vacations = fields.Float(string="Días pendientes", compute="_compute_vacations")
    anticipated_vacations = fields.Float(string="Días anticipados", compute="_compute_vacations")

    total_days_taken = fields.Float(
        string="Días tomados",
        compute="_compute_vacations",
        help="Corresponde a los días totales tomados por concepto de vacaciones",
    )

    leaves_ids = fields.Many2many("hr.leave", compute="_compute_vacations", string="Vacaciones", readonly=True)

    @api.depends("employee_id")
    def _compute_name(self):
        for book in self:
            book.name = "LIBRO DE VACACIONES " + book.employee_id.name.upper() if book.employee_id else "LIBRO DE VACACIONES"

    @api.depends("contract_id.contract_date_end", "contract_id.date_end")
    def _compute_date_to(self):
        for book in self:
            if book.contract_id and hasattr(book.contract_id, "_l10n_co_payroll_get_end_date"):
                book.date_to = book.contract_id._l10n_co_payroll_get_end_date() or fields.Date.today()
            else:
                book.date_to = fields.Date.today()

    @api.depends("contract_id.contract_date_start", "contract_id.date_start")
    def _compute_date_start_contract(self):
        for book in self:
            if book.contract_id and hasattr(book.contract_id, "_l10n_co_payroll_get_start_date"):
                book.date_start_contract = book.contract_id._l10n_co_payroll_get_start_date()
            else:
                book.date_start_contract = False

    @api.depends("employee_id", "contract_id")
    def _compute_vacations(self):
        for book in self:
            if not book.employee_id or not book.contract_id:
                book.accrued_vacations = 0
                book.anticipated_vacations = 0
                book.vacations_taken = 0
                book.total_days_taken = 0
                book.compensated_vacations = 0
                book.remaining_vacations = 0
                book.leaves_ids = self.env["hr.leave"]
                continue

            allocations = self.env["hr.leave.allocation"].search(
                [
                    ("employee_id", "=", book.employee_id.id),
                    ("contract_id", "=", book.contract_id.id),
                    ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
                    ("state", "not in", ("cancel", "refuse")),
                ]
            )
            leaves = self.env["hr.leave"].search(
                [
                    ("employee_id", "=", book.employee_id.id),
                    ("contract_id", "=", book.contract_id.id),
                    ("state", "=", "validate"),
                    ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
                ],
                order="date_from asc, id asc",
            )
            book.accrued_vacations = sum(allocations.mapped("number_of_days"))
            book.anticipated_vacations = sum(allocations.mapped("anticipated_vacations"))
            book.vacations_taken = 0
            book.total_days_taken = 0
            book.compensated_vacations = 0
            book.leaves_ids = leaves
            for leave in leaves:
                if leave.payslip_input_id:
                    book.compensated_vacations += leave.number_of_days
                else:
                    book.vacations_taken += leave.number_of_days
                book.total_days_taken += leave.number_of_days
            book.remaining_vacations = book.accrued_vacations - book.total_days_taken

    @api.model
    def generate_book(self):
        allocations = self.env["hr.leave.allocation"].search(
            [
                ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
                ("state", "not in", ("cancel", "refuse")),
                ("contract_id", "!=", False),
            ]
        )
        existing_contract_ids = set(self.search([("contract_id", "in", allocations.mapped("contract_id").ids)]).mapped("contract_id").ids)
        for allocation in allocations:
            if allocation.contract_id.id not in existing_contract_ids:
                self.create({"contract_id": allocation.contract_id.id})
                existing_contract_ids.add(allocation.contract_id.id)
