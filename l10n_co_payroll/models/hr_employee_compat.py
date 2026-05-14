from odoo import api, fields, models


TYPE_PAYMENT_SELECTION = [
    ("monthly", "Monthly"),
    ("first_half", "First half of month"),
    ("second_half", "Second half of month"),
    ("both_fortnight", "Both fortnights"),
]


class HrEmployeeColombia(models.Model):
    _inherit = "hr.employee"

    address_home_id = fields.Many2one("res.partner", string="Home Address")
    eps_id = fields.Many2one("res.partner", string="EPS")
    fp_id = fields.Many2one("res.partner", string="Fondo de Pensiones")
    fc_id = fields.Many2one("res.partner", string="Fondo de Cesantias")
    ccf_id = fields.Many2one("res.partner", string="Caja de compensacion familiar")
    nivel_arl = fields.Selection(
        selection=[
            ("1", "Nivel 1"),
            ("2", "Nivel 2"),
            ("3", "Nivel 3"),
            ("4", "Nivel 4"),
            ("5", "Nivel 5"),
        ],
        string="Nivel de riesgo ARL",
    )
    afc = fields.Integer(string="Valor aporte mensual a cuenta AFC")
    type_payment_afc = fields.Selection(selection=TYPE_PAYMENT_SELECTION, string="Type Payment AFC", default="monthly")
    avc = fields.Integer(string="Valor aporte mensual a cuenta AVC")
    type_payment_avc = fields.Selection(selection=TYPE_PAYMENT_SELECTION, string="Type Payment AVC", default="monthly")
    fpv = fields.Integer(string="Valor aporte mensual a FPV")
    type_payment_fpv = fields.Selection(selection=TYPE_PAYMENT_SELECTION, string="Type Payment FPV", default="monthly")
    int_vivienda = fields.Integer(string="Valor mensual intereses de vivienda")
    med_prep = fields.Integer(string="Valor mensual medicina prepagada")
    dependientes = fields.Integer(string="Valor mensual dependientes")
    pensionado = fields.Boolean(string="Es pensionado?")
    exento_transporte = fields.Boolean(string="Exento subsidio de transporte")
    transportation_payment = fields.Selection(
        selection=[
            ("normal", "Auxilio Normal"),
            ("sin_dominical_festivo", "Auxilio sin dominicales ni festivos"),
            ("sin_recargos", "Auxilio sin recargos"),
            ("auxilio_sin_sueldo", "Auxilio sin considerar sueldo"),
        ],
        string="Auxilio de Transporte",
        default="normal",
    )
    vacations_payment = fields.Boolean(string="Incluye pago de vacaciones", default=False)
    send_previous_provisions = fields.Boolean(string="Enviar provisiones previas")
    analytic_account = fields.Many2one("account.analytic.account", string="Analytic Account")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    contract_id = fields.Many2one(
        "hr.version",
        string="Current Payroll Record",
        compute="_compute_l10n_co_payroll_contract_id",
    )
    bank_account_id = fields.Many2many(
        "res.partner.bank",
        string="Bank Accounts (compat)",
        compute="_compute_l10n_co_payroll_bank_account_id",
    )

    @api.depends("version_id")
    def _compute_l10n_co_payroll_contract_id(self):
        for employee in self:
            employee.contract_id = employee.version_id

    @api.depends("bank_account_ids")
    def _compute_l10n_co_payroll_bank_account_id(self):
        for employee in self:
            employee.bank_account_id = employee.bank_account_ids

    def _l10n_co_payroll_get_home_partner(self):
        self.ensure_one()
        return (
            self.address_home_id
            or getattr(self, "work_contact_id", False)
            or getattr(self, "user_partner_id", False)
            or (self.user_id.partner_id if self.user_id else False)
        )

    def _l10n_co_payroll_get_contracts(self, active_only=False, include_inactive=True):
        self.ensure_one()
        employee = self.with_context(active_test=False) if include_inactive else self
        versions = employee.version_ids
        if active_only:
            versions = versions.filtered(lambda version: version._l10n_co_payroll_is_active_contract() if hasattr(version, "_l10n_co_payroll_is_active_contract") else False)
        return versions.sorted(key=lambda version: (version._l10n_co_payroll_get_start_date() or fields.Date.today(), version.id), reverse=True)

    def _l10n_co_payroll_get_active_contract(self):
        self.ensure_one()
        current_version = self.version_id or getattr(self, "current_version_id", False)
        if current_version:
            return current_version
        return self._l10n_co_payroll_get_contracts(active_only=True, include_inactive=True)[:1]
