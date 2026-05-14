import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


SCHEDULE_TO_PERIOD = {
    "weekly": "1",
    "bi-weekly": "3",
    "semi-monthly": "4",
    "monthly": "5",
}


class HrVersion(models.Model):
    _inherit = "hr.version"

    state = fields.Selection(
        selection=[
            ("draft", "Nuevo"),
            ("open", "En proceso"),
            ("close", "Expirado"),
            ("cancel", "Cancelado"),
        ],
        string="Estado",
        compute="_compute_l10n_co_payroll_state",
    )

    tipo_salario = fields.Selection(
        selection=[
            ("aprendiz Sena", "Aprendiz Sena"),
            ("integral", "Integral"),
            ("practicante", "Practicante"),
            ("tradicional", "Tradicional"),
            ("pasante", "Pasante"),
        ],
        string="Tipo de salario",
        required=True,
        default="tradicional",
        tracking=True,
    )
    salario_variable = fields.Boolean(string="Salario variable")
    area_trabajo = fields.Selection(
        selection=[
            ("administracion", "Administracion"),
            ("produccion", "Produccion"),
            ("ventas", "Ventas"),
        ],
        string="Area de trabajo",
        required=True,
        default="administracion",
    )
    saldo_prima = fields.Float(string="Saldo prima", digits=(12, 2))
    saldo_cesantias = fields.Float(string="Saldo cesantias", digits=(12, 2))
    saldo_intereses_cesantias = fields.Float(string="Saldo intereses cesantias", digits=(12, 2))
    saldo_vacaciones = fields.Float(string="Saldo vacaciones", digits=(12, 2))
    retencion_fuente = fields.Selection(
        selection=[
            ("procedimiento1", "Procedimiento 1"),
            ("procedimiento2", "Procedimiento 2"),
        ],
        string="Retencion en la fuente",
        default="procedimiento1",
    )
    retefuente_table_value_ids = fields.Many2many(
        "retefuente.table",
        compute="_compute_retefuente_table_value_ids",
        help="Variable tecnica para obtener la tabla de retencion en la fuente.",
    )
    withholding_percentage_id = fields.Many2one(
        "historical.withholdings",
        string="Withholding tax percentage",
        help="Percentage used for the withholding calculation for the period.",
    )
    fecha_corte = fields.Date(string="Fecha corte")
    fecha_corte_required = fields.Boolean(
        string="Fecha corte requerida",
        compute="_compute_fecha_corte_required",
        help="Verdadero si existen salarios previos registrados.",
    )
    traza_atributo_salario_ids = fields.One2many("traza.atributo", "id_objeto", string="Ultimos salarios")
    intervalo_calendario_ids = fields.One2many("intervalo.calendario", "contract_id", string="Calendarios")
    new_entries_ids = fields.One2many("new.entry", "contract_id", string="Novedades del contrato")
    warning_message = fields.Char(readonly=True)
    periodo_de_nomina = fields.Selection(
        selection=[
            ("1", "Semanal"),
            ("2", "Decenal"),
            ("3", "Catorcenal"),
            ("4", "Quincenal"),
            ("5", "Mensual"),
        ],
        string="Periodo de nomina",
        compute="_compute_periodo_de_nomina",
        store=True,
        readonly=False,
        required=True,
        default="5",
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Cuenta analitica",
        compute="_compute_l10n_co_payroll_analytic_account_id",
    )

    @api.depends("employee_id.current_version_id", "contract_date_start", "contract_date_end", "date_start", "date_end")
    def _compute_l10n_co_payroll_state(self):
        today = fields.Date.context_today(self)
        for version in self:
            current_version = getattr(version.employee_id, "current_version_id", False) or getattr(
                version.employee_id, "version_id", False
            )
            start_date = version._l10n_co_payroll_get_start_date() if version.employee_id else False
            end_date = version._l10n_co_payroll_get_end_date() if version.employee_id else False
            if not version.employee_id or not start_date:
                version.state = "draft"
            elif current_version and current_version.id == version.id and (not end_date or end_date >= today):
                version.state = "open"
            elif end_date and end_date < today:
                version.state = "close"
            else:
                version.state = "cancel"

    @api.depends("schedule_pay")
    def _compute_periodo_de_nomina(self):
        for version in self:
            version.periodo_de_nomina = SCHEDULE_TO_PERIOD.get(version.schedule_pay, version.periodo_de_nomina or "5")

    @api.depends("analytic_distribution")
    def _compute_l10n_co_payroll_analytic_account_id(self):
        for version in self:
            analytic_account_id = False
            distribution = version.analytic_distribution or {}
            if isinstance(distribution, dict):
                numeric_keys = [(int(key), value) for key, value in distribution.items() if str(key).isdigit()]
                if numeric_keys:
                    numeric_keys.sort(key=lambda item: (-item[1], item[0]))
                    analytic_account_id = numeric_keys[0][0]
            version.analytic_account_id = analytic_account_id

    @api.depends("traza_atributo_salario_ids")
    def _compute_fecha_corte_required(self):
        for version in self:
            version.fecha_corte_required = bool(version.traza_atributo_salario_ids)

    def _compute_retefuente_table_value_ids(self):
        table_values = self.env["retefuente.table"].search([])
        for version in self:
            version.retefuente_table_value_ids = table_values
            if version.retencion_fuente != "procedimiento2" or version.withholding_percentage_id:
                continue
            withholding = version._l10n_co_payroll_get_current_withholding_percentage()
            if withholding:
                version.withholding_percentage_id = withholding

    @api.onchange("new_entries_ids")
    def _onchange_new_entries_ids(self):
        for version in self:
            version.warning_message = False
            if len(version._origin.new_entries_ids) != len(version.new_entries_ids):
                continue
            for index, entry in enumerate(version.new_entries_ids):
                if version._origin.new_entries_ids[index].type_payment != entry.type_payment:
                    version.warning_message = (
                        "Tenga en cuenta los cambios en el Tipo de Pago. "
                        "Estos pueden causar variaciones en la nomina del ultimo mes a liquidar."
                    )
                    break

    @api.onchange("retencion_fuente")
    def _onchange_retencion_fuente(self):
        for version in self:
            if version.retencion_fuente == "procedimiento1":
                version.withholding_percentage_id = False
                continue
            version.withholding_percentage_id = version._l10n_co_payroll_get_current_withholding_percentage()

    def _l10n_co_payroll_get_current_withholding_percentage(self):
        self.ensure_one()
        if not self.id:
            return self.withholding_percentage_id
        today = fields.Date.context_today(self)
        return self.env["historical.withholdings"].search(
            [
                ("contract_id", "=", self.id),
                ("period_from", "<=", today),
                ("period_to", ">=", today),
            ],
            limit=1,
        )

    @api.model
    def _l10n_co_payroll_get_trace_variable(self, target_date):
        trace_variable = self.env["traza.variable"].search(
            [
                ("fecha_desde", "<=", target_date),
                ("fecha_hasta", ">=", target_date),
            ],
            limit=1,
        )
        if trace_variable:
            return trace_variable
        return self.env["traza.variable"].search(
            [("fecha_hasta", "<=", target_date)],
            order="fecha_hasta desc",
            limit=1,
        )

    @api.model
    def cron_calcular_porcentaje_retencion(self, day=False, month=False, year=False):
        if day and month and year:
            today = date(year, month, day)
        else:
            today = fields.Date.context_today(self)

        _logger.info("Fecha calculo retencion: %s", today)
        if today.month not in (1, 7) or today.day != 10:
            return True

        trace_variable = self._l10n_co_payroll_get_trace_variable(today)
        if not trace_variable or not trace_variable.valor_uvt:
            _logger.warning("No existe traza.variable con UVT configurado para la fecha %s.", today)
            return True

        versions = self.search(
            [
                ("employee_id", "!=", False),
                ("retencion_fuente", "=", "procedimiento2"),
                ("contract_date_start", "!=", False),
                ("contract_date_start", "<=", today),
                "|",
                ("contract_date_end", "=", False),
                ("contract_date_end", ">", today),
            ]
        ).filtered(
            lambda version: not version.withholding_percentage_id or version.withholding_percentage_id.period_to < today
        )

        for version in versions:
            start_date = version._l10n_co_payroll_get_start_date()
            if not start_date:
                continue

            if today.month == 1:
                minimum_start_date = date(today.year - 1, 7, 1)
                period_from = date(today.year - 1, 1, 1)
                period_to = date(today.year, 1, 1)
            else:
                minimum_start_date = date(today.year, 1, 1)
                period_from = date(today.year - 1, 7, 1)
                period_to = date(today.year, 7, 1)

            if start_date > minimum_start_date:
                continue

            payslips = self.env["hr.payslip"].search(
                [
                    ("version_id", "=", version.id),
                    ("date_to", ">=", period_from),
                    ("date_to", "<", period_to),
                    ("state", "in", ("done", "validated", "paid")),
                ],
                order="date_to",
            )
            if not payslips:
                continue

            base_gravable = 0.0
            base_gravable_prima = 0.0
            num_meses = 0
            actual_period = False
            for payslip in payslips:
                line_total = sum(payslip.line_ids.filtered(lambda line: line.code == "BAS_GRA_RTF").mapped("total"))
                if payslip.liquidar_por != "prima":
                    base_gravable += line_total
                else:
                    base_gravable_prima += line_total

                payslip_period = (payslip.date_to.year, payslip.date_to.month)
                if actual_period != payslip_period:
                    num_meses += 1
                    actual_period = payslip_period

            base_gravable += base_gravable_prima
            if not base_gravable or not num_meses:
                continue
            if num_meses == 12:
                num_meses += 1

            base_gravable = round(base_gravable / num_meses, -3)
            if not base_gravable:
                continue

            base_gravable_uvt = round(base_gravable / trace_variable.valor_uvt, 2)
            valor_uvt_tabla = 0.0
            for table_line in version.retefuente_table_value_ids:
                if table_line.range_from <= base_gravable_uvt < table_line.range_to:
                    valor_uvt_tabla = round(
                        ((base_gravable_uvt - table_line.range_from) * (table_line.marginal_rate / 100))
                        + table_line.uvt_added,
                        2,
                    )
                    break

            porcentaje_fijo_final = round(((valor_uvt_tabla * trace_variable.valor_uvt) / base_gravable) * 100, 2)
            withholding = self.env["historical.withholdings"].create(
                {
                    "percentage_value": porcentaje_fijo_final,
                    "contract_id": version.id,
                }
            )
            withholding.onchange_percentage_value(today)
            version.withholding_percentage_id = withholding
        return True

    def _l10n_co_payroll_get_start_date(self):
        self.ensure_one()
        return self.contract_date_start or self.date_start

    def _l10n_co_payroll_get_end_date(self):
        self.ensure_one()
        return self.contract_date_end or self.date_end

    def _l10n_co_payroll_get_vacation_nextcall(self, reference_date=None):
        self.ensure_one()
        start_date = self._l10n_co_payroll_get_start_date()
        reference_date = reference_date or fields.Date.context_today(self)
        if not start_date or not reference_date:
            return False
        try:
            last_assignment = reference_date.replace(day=start_date.day)
            if reference_date < last_assignment:
                last_assignment -= relativedelta(months=1)
        except ValueError:
            last_assignment = reference_date.replace(day=1) + relativedelta(day=31)
            if reference_date < last_assignment:
                last_assignment = (last_assignment - relativedelta(months=1)) + relativedelta(day=31)
        return last_assignment + relativedelta(months=1)

    def _l10n_co_payroll_is_active_contract(self):
        self.ensure_one()
        current_version = getattr(self.employee_id, "version_id", False) or getattr(self.employee_id, "current_version_id", False)
        return bool(current_version and current_version.id == self.id)

    def _l10n_co_payroll_supports_social_benefits(self):
        self.ensure_one()
        return self.tipo_salario in ("tradicional", "integral")

    def _l10n_co_payroll_get_balance_snapshot(self):
        self.ensure_one()
        return {
            "saldo_prima": getattr(self, "saldo_prima", 0.0),
            "saldo_cesantias": getattr(self, "saldo_cesantias", 0.0),
            "saldo_intereses_cesantias": getattr(self, "saldo_intereses_cesantias", 0.0),
            "saldo_vacaciones": getattr(self, "saldo_vacaciones", 0.0),
            "fecha_corte": getattr(self, "fecha_corte", False),
        }

    @api.model_create_multi
    def create(self, vals_list):
        versions = super().create(vals_list)
        for version in versions.filtered(
            lambda record: record.retencion_fuente == "procedimiento2" and record.withholding_percentage_id
        ):
            version.withholding_percentage_id.contract_id = version.id
        return versions

    def write(self, vals):
        previous_withholding_map = {version.id: version.withholding_percentage_id for version in self}
        res = super().write(vals)
        if "withholding_percentage_id" in vals and not vals["withholding_percentage_id"]:
            for version in self:
                previous_withholding = previous_withholding_map.get(version.id)
                if previous_withholding:
                    previous_withholding.unlink()
        for version in self.filtered(
            lambda record: record.retencion_fuente == "procedimiento2" and record.withholding_percentage_id
        ):
            if version.withholding_percentage_id.contract_id != version:
                version.withholding_percentage_id.contract_id = version.id
        return res
