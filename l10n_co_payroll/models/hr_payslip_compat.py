import base64
import calendar
from datetime import date, timedelta
from math import floor

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import date_utils

from . import matematica


LIQUIDAR_POR_SELECTION = [
    ("nomina", "Nomina"),
    ("prima", "Prima"),
    ("cesantias", "Cesantias"),
    ("intereses_cesantias", "Intereses de cesantias"),
    ("vacaciones", "Vacaciones"),
    ("definitiva", "Definitiva"),
]

TIPO_VARIACION_SALARIO_SELECTION = [
    ("fijo", "Fijo"),
    ("fijo_sin_variacion", "Fijo sin variacion"),
    ("fijo_con_variacion", "Fijo con variacion"),
    ("variable", "Variable"),
]


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    contract_id = fields.Many2one(
        "hr.version",
        string="Contrato salarial",
        related="version_id",
        store=True,
        readonly=False,
    )
    contract_struct_id = fields.Many2one(
        "hr.payroll.structure.type",
        string="Estructura salarial del contrato",
        related="contract_id.structure_type_id",
        readonly=True,
    )
    liquidar_por = fields.Selection(selection=LIQUIDAR_POR_SELECTION, string="Liquidar por", default="nomina", required=True)
    warning_message = fields.Char(string="Advertencia", compute="_compute_l10n_co_payroll_warning_message")
    payment_mean_id = fields.Many2one(
        "l10n_co_payroll.payment_mean",
        string="Medio de pago",
        default=lambda self: self.env["l10n_co_payroll.payment_mean"]._get_default_payment_mean(),
    )
    dias = fields.Float(string="Dias", compute="_compute_l10n_co_payroll_period_base")
    dias_hecho = fields.Float(string="Dias hecho", compute="_compute_l10n_co_payroll_month_progress")
    first_day_month = fields.Date(string="Dia inicial del mes", compute="_compute_l10n_co_payroll_period_base")
    last_day_month = fields.Date(string="Dia final del mes", compute="_compute_l10n_co_payroll_period_base")
    date_from_cesantias = fields.Date(string="Fecha desde cesantias-definitiva", compute="_compute_l10n_co_payroll_accrual_ranges")
    date_from_prima = fields.Date(string="Fecha desde prima-definitiva", compute="_compute_l10n_co_payroll_accrual_ranges")
    days_paid = fields.Float(string="Dias ya liquidados en el mes", compute="_compute_l10n_co_payroll_month_progress")
    dias_a_pagar = fields.Float(string="Dias a liquidar en el periodo", compute="_compute_l10n_co_payroll_days", store=True, readonly=False)
    dias_prima = fields.Float(string="Dias prima", compute="_compute_l10n_co_payroll_days", store=True, readonly=False)
    dias_trabajados = fields.Float(string="Dias trabajados", compute="_compute_l10n_co_payroll_days", store=True, readonly=False)
    dias_vacaciones = fields.Float(string="Dias vacaciones", compute="_compute_l10n_co_payroll_days", store=True, readonly=False)
    days_month_date_from = fields.Integer(string="Dias del mes de la fecha desde", compute="_compute_l10n_co_payroll_days", store=True, readonly=False)
    dias_a_pagar_hecho = fields.Float(string="Dias pagados hecho", compute="_compute_l10n_co_payroll_month_progress")
    dias_incapacidad_comun = fields.Float(string="Dias incapacidad comun", default=0.0)
    dias_incapacidad_comun_hecho = fields.Float(string="Dias incapacidad comun hecho", compute="_compute_l10n_co_payroll_month_progress")
    dias_licencia_mat_pat = fields.Float(string="Dias licencia Mat/Pat", default=0.0)
    dias_licencia_mat_pat_hecho = fields.Float(string="Dias licencia Mat/Pat hecho", compute="_compute_l10n_co_payroll_month_progress")
    dias_vacaciones_compensadas = fields.Float(string="Dias vacaciones compensadas", default=0.0)
    dias_vacaciones_hecho = fields.Float(string="Dias vacaciones hecho", compute="_compute_l10n_co_payroll_month_progress")
    dias_cesantias = fields.Float(string="Dias cesantias", compute="_compute_l10n_co_payroll_accrual_ranges")
    dias_intereses_cesantias = fields.Float(string="Dias intereses cesantias", compute="_compute_l10n_co_payroll_accrual_ranges")
    nod_paid_leaves = fields.Float(string="Ausencias pagas", default=0.0)
    nod_unpaid_leaves = fields.Float(string="Dias suspension contrato", default=0.0)
    nod_unpaid_leaves_hecho = fields.Float(string="Dias suspension contrato hecho", compute="_compute_l10n_co_payroll_month_progress")
    valor_incapacidad_comun = fields.Float(string="Valor incapacidad comun", compute="_compute_l10n_co_payroll_reference_values")
    valor_licencia_mat_pat = fields.Float(string="Valor licencia maternidad/paternidad", compute="_compute_l10n_co_payroll_reference_values")
    dia_inicio_mes_anterior = fields.Date(string="Dia inicial del mes anterior", compute="_compute_l10n_co_payroll_period_base")
    dia_fin_mes_anterior = fields.Date(string="Dia final del mes anterior", compute="_compute_l10n_co_payroll_period_base")
    first_day_month_date_to = fields.Date(string="Primer dia del mes de la fecha hasta", compute="_compute_l10n_co_payroll_period_base")
    sueldo_proyectado_pendiente_hasta = fields.Float(string="Sueldo proyectado pendiente hasta fecha de liquidacion", compute="_compute_l10n_co_payroll_period_base")
    dias_trabajados_mes_hecho = fields.Float(string="Dias trabajados mes hecho", compute="_compute_l10n_co_payroll_month_progress")
    promedio_variable_sin_extras_ni_rdominicalf_360 = fields.Float(
        string="Promedio variable diario sin extras ni recargos dominicales 360 dias",
        compute="_compute_l10n_co_payroll_reference_values",
    )
    promedio_wage_360 = fields.Float(string="Promedio salario 360 dias", compute="_compute_l10n_co_payroll_reference_values")
    promedio_sal_aux_tras_360 = fields.Float(string="Promedio salario + aux tras 360 dias", compute="_compute_l10n_co_payroll_reference_values")
    promedio_sal_aux_tras_180 = fields.Float(string="Promedio salario + aux tras 180 dias", compute="_compute_l10n_co_payroll_reference_values")
    promedio_sal_aux_tras_90 = fields.Float(string="Promedio salario + aux tras 90 dias", compute="_compute_l10n_co_payroll_reference_values")
    base_fondo_solidaridad_hecho = fields.Float(string="Base para fondo de solidaridad hecho", compute="_compute_l10n_co_payroll_reference_values")
    subsistence_fund_paid = fields.Float(string="Fondo de solidaridad-subsistencia pagado", compute="_compute_l10n_co_payroll_reference_values")
    solidarity_fund_paid = fields.Float(string="Fondo de solidaridad-solidaridad pagado", compute="_compute_l10n_co_payroll_reference_values")
    smlv = fields.Integer(string="Salario minimo mensual", compute="_compute_l10n_co_payroll_reference_values")
    aux_trans = fields.Integer(string="Auxilio de transporte", compute="_compute_l10n_co_payroll_reference_values")
    valor_uvt = fields.Integer(string="Valor UVT", compute="_compute_l10n_co_payroll_reference_values")
    wage = fields.Monetary(string="Sueldo", related="version_id.wage", currency_field="currency_id", readonly=True)
    tipo_variacion_salario = fields.Selection(
        selection=TIPO_VARIACION_SALARIO_SELECTION,
        string="Tipo de salario para esta nomina",
        compute="_compute_l10n_co_payroll_salary_variation",
        store=True,
        readonly=False,
    )
    ibc_seguridad_social_mes_anterior = fields.Float(string="IBC seguridad social mes anterior", compute="_compute_l10n_co_payroll_reference_values")
    valor_dia_reemplazo_hecho = fields.Float(string="Valor del dia reemplazo hecho", compute="_compute_l10n_co_payroll_month_progress")
    last_payslip = fields.Boolean(string="Ultima nomina", default=False)
    previous_payslips_done = fields.Many2many("hr.payslip", string="Nominas previas", compute="_compute_l10n_co_payroll_previous_payslips_done")
    exempt_rent = fields.Float(string="Renta exenta actual", default=0.0)
    exempt_rent_accumulated = fields.Float(string="Renta exenta acumulada", compute="_compute_l10n_co_payroll_exempt_rent_accumulated")
    correo_enviado = fields.Boolean(string="Correo enviado", default=False)
    template_id = fields.Many2one(
        "mail.template",
        string="Plantilla correo",
        domain="[('model', '=', 'hr.payslip')]",
        default=lambda self: self.env.ref("l10n_co_payroll.hr_payroll_template", raise_if_not_found=False),
    )
    move_id_pago = fields.Many2one("account.move", string="Asiento de pago")
    third_move_id = fields.Many2one("account.move", string="Asiento de pago a terceros")

    def _l10n_co_payroll_get_trace_variable(self):
        self.ensure_one()
        target_date = self.date_to or self.date_from or fields.Date.context_today(self)
        if self.contract_id and hasattr(self.contract_id, "_l10n_co_payroll_get_trace_variable"):
            return self.contract_id._l10n_co_payroll_get_trace_variable(target_date)
        trace_variable = self.env["traza.variable"].search(
            [("fecha_desde", "<=", target_date), ("fecha_hasta", ">=", target_date)],
            limit=1,
        )
        if trace_variable:
            return trace_variable
        return self.env["traza.variable"].search([("fecha_hasta", "<=", target_date)], order="fecha_hasta desc", limit=1)

    def _l10n_co_payroll_get_default_mail_template(self):
        return self.env.ref("l10n_co_payroll.hr_payroll_template", raise_if_not_found=False)

    def _get_localdict(self):
        self.ensure_one()
        localdict = super()._get_localdict()
        contract = self.contract_id or self.version_id
        localdict["employee"] = self.employee_id
        localdict["version"] = self.version_id
        localdict["version_id"] = self.version_id
        localdict["contract"] = contract
        localdict["contract_id"] = contract
        return localdict

    def _l10n_co_payroll_validate_trace_variable_configuration(self):
        for payslip in self:
            target_date = payslip.date_to or payslip.date_from
            if not target_date:
                continue
            trace_variable = payslip._l10n_co_payroll_get_trace_variable()
            if trace_variable and trace_variable.smlv > 0 and trace_variable.valor_uvt > 0:
                continue
            raise ValidationError(
                _(
                    "No existe una traza variable vigente con salario minimo y UVT validos para la fecha %(date)s. "
                    "Configure la traza variable antes de liquidar la nomina.",
                    date=target_date,
                )
            )

    def _l10n_co_payroll_get_vacation_allocation(self):
        self.ensure_one()
        if not self.employee_id or not self.contract_id:
            return self.env["hr.leave.allocation"]
        return self.env["hr.leave.allocation"].search(
            [
                ("employee_id", "=", self.employee_id.id),
                ("contract_id", "=", self.contract_id.id),
                ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
                ("state", "=", "validate"),
            ],
            limit=1,
        )

    def _l10n_co_payroll_validate_special_liquidation(self):
        for payslip in self:
            if not payslip.employee_id or not payslip.contract_id:
                continue
            if not payslip._validate_date():
                raise ValidationError(
                    _(
                        "Ya existe liquidacion de %(liquidation)s dentro del periodo seleccionado para %(employee)s.",
                        liquidation=payslip.liquidar_por,
                        employee=payslip.employee_id.name,
                    )
                )
            contract_end = (
                payslip.contract_id._l10n_co_payroll_get_end_date()
                if hasattr(payslip.contract_id, "_l10n_co_payroll_get_end_date")
                else payslip.contract_id.contract_date_end or payslip.contract_id.date_end
            )
            if payslip.liquidar_por == "definitiva" and not contract_end:
                raise ValidationError(
                    _(
                        "Antes de liquidar de manera definitiva a %(employee)s, debe definir la fecha final del contrato.",
                        employee=payslip.employee_id.name,
                    )
                )
            supports_social_benefits = (
                payslip.contract_id._l10n_co_payroll_supports_social_benefits()
                if hasattr(payslip.contract_id, "_l10n_co_payroll_supports_social_benefits")
                else getattr(payslip.contract_id, "tipo_salario", False) in ("tradicional", "integral")
            )
            if not supports_social_benefits or payslip.liquidar_por not in ("nomina", "vacaciones", "definitiva"):
                continue
            allocation = payslip._l10n_co_payroll_get_vacation_allocation()
            if not allocation:
                raise UserError(
                    _(
                        "Valide que %(employee)s tenga una asignacion de vacaciones activa para el registro salarial %(contract)s.",
                        employee=payslip.employee_id.name,
                        contract=payslip.contract_id.display_name,
                    )
                )

    def _l10n_co_payroll_get_previous_period_slips(self, start_date, end_date, types=None):
        self.ensure_one()
        slips = self.previous_payslips_done.filtered(
            lambda slip: slip.date_from
            and slip.date_to
            and slip.date_from >= start_date
            and slip.date_to <= end_date
            and slip.date_to < (self.date_from or slip.date_to + timedelta(days=1))
        )
        if types:
            slips = slips.filtered(lambda slip: slip.liquidar_por in types)
        return slips.sorted("date_from")

    def _l10n_co_payroll_get_variable_average(self, days_window):
        self.ensure_one()
        if not self.contract_id.salario_variable:
            return 0.0
        if not self.date_from:
            return 0.0
        start_date = max(
            self.contract_id._l10n_co_payroll_get_start_date() or self.date_from,
            self.date_from - timedelta(days=days_window),
        )
        slips = self._l10n_co_payroll_get_previous_period_slips(start_date, self.date_from - timedelta(days=1), ("nomina", "vacaciones"))
        excluded_codes = {
            "SUELDO",
            "AUX_TRA",
            "VAC",
            "LICMP",
            "INCAPACIDAD_COMUN",
            "NET",
            "TOTALDEV",
            "TOTALDED",
            "TOTAL",
            "BAS_FS",
            "BAS_SEG_SOC_AFP_EPS",
            "BAS_PRE_SOC",
        }
        variable_total = 0.0
        reference_days = 0.0
        for slip in slips:
            reference_days += slip.dias_trabajados or slip.dias_a_pagar or slip.dias or 0.0
            for line in slip.line_ids:
                if not line.category_id or line.category_id.code != "DEV":
                    continue
                if line.code in excluded_codes:
                    continue
                variable_total += line.total
        if not reference_days:
            return 0.0
        return round(variable_total / reference_days, 2)

    @api.depends("employee_id", "contract_id", "date_from", "date_to", "liquidar_por")
    def _compute_l10n_co_payroll_previous_payslips_done(self):
        payslip_model = self.env["hr.payslip"]
        for payslip in self:
            if not payslip.employee_id or not payslip.contract_id or not payslip.date_from:
                payslip.previous_payslips_done = payslip_model
                continue
            contract_start = payslip.contract_id._l10n_co_payroll_get_start_date() or payslip.date_from
            if payslip.liquidar_por == "definitiva":
                start_period = contract_start
            else:
                start_period = max(payslip.date_from - relativedelta(years=1, months=1), contract_start).replace(day=1)
            payslip.previous_payslips_done = payslip_model.search(
                [
                    ("id", "!=", payslip.id or payslip._origin.id or 0),
                    ("employee_id", "=", payslip.employee_id.id),
                    ("contract_id", "=", payslip.contract_id.id),
                    ("state", "in", ("done", "validated", "paid")),
                    ("date_to", ">=", start_period),
                    ("date_from", "<=", payslip.date_to or payslip.date_from),
                ],
                order="date_from, date_to",
            )

    @api.depends("date_from", "date_to", "liquidar_por", "contract_id", "wage")
    def _compute_l10n_co_payroll_period_base(self):
        for payslip in self:
            payslip.dias = 0.0
            payslip.first_day_month = False
            payslip.last_day_month = False
            payslip.first_day_month_date_to = False
            payslip.dia_inicio_mes_anterior = False
            payslip.dia_fin_mes_anterior = False
            payslip.sueldo_proyectado_pendiente_hasta = 0.0

            if not payslip.date_from or not payslip.date_to or payslip.date_to < payslip.date_from:
                continue

            payslip.dias = matematica.duracion360(payslip.date_from, payslip.date_to)
            payslip.first_day_month = payslip.date_from.replace(day=1)
            payslip.last_day_month = payslip.date_to.replace(day=calendar.monthrange(payslip.date_to.year, payslip.date_to.month)[1])
            payslip.first_day_month_date_to = payslip.date_to.replace(day=1)
            previous_month_end = payslip.first_day_month - timedelta(days=1)
            payslip.dia_inicio_mes_anterior = previous_month_end.replace(day=1)
            payslip.dia_fin_mes_anterior = previous_month_end

            if payslip.liquidar_por != "prima" or not payslip.contract_id:
                continue

            last_nomina = self.search(
                [
                    ("id", "!=", payslip.id or payslip._origin.id or 0),
                    ("employee_id", "=", payslip.employee_id.id),
                    ("contract_id", "=", payslip.contract_id.id),
                    ("liquidar_por", "=", "nomina"),
                    ("state", "in", ("done", "validated", "paid")),
                    ("date_to", "<=", payslip.date_to),
                ],
                order="date_to desc",
                limit=1,
            )
            if not last_nomina:
                continue

            dias_proyectados = matematica.duracion360(last_nomina.date_to + timedelta(days=1), payslip.last_day_month)
            trace_variable = payslip._l10n_co_payroll_get_trace_variable()
            subsidio_transporte_proyectado = 0.0
            if (
                trace_variable
                and payslip.contract_id.tipo_salario == "tradicional"
                and payslip.wage
                and payslip.wage < 2 * trace_variable.smlv
            ):
                subsidio_transporte_proyectado = trace_variable.aux_trans * dias_proyectados / 30
            payslip.sueldo_proyectado_pendiente_hasta = round((dias_proyectados * (payslip.wage or 0.0) / 30) + subsidio_transporte_proyectado, 2)

    @api.depends("liquidar_por", "date_from", "date_to", "contract_id", "previous_payslips_done")
    def _compute_l10n_co_payroll_accrual_ranges(self):
        for payslip in self:
            payslip.date_from_prima = False
            payslip.date_from_cesantias = False
            payslip.dias_cesantias = 0.0
            payslip.dias_intereses_cesantias = 0.0

            if not payslip.contract_id or not payslip.date_from or not payslip.date_to:
                continue

            contract_start = payslip.contract_id._l10n_co_payroll_get_start_date() or payslip.date_from
            if payslip.liquidar_por == "definitiva":
                liquidaciones_prima = payslip.previous_payslips_done.filtered(lambda slip: slip.liquidar_por == "prima").sorted("date_from", reverse=True)
                if liquidaciones_prima:
                    payslip.date_from_prima = liquidaciones_prima[0].date_to + timedelta(days=1)
                else:
                    payslip.date_from_prima = max(
                        contract_start,
                        date(payslip.date_to.year, 7 if payslip.date_to.month >= 7 else 1, 1),
                    )

                liquidaciones_cesantias = payslip.previous_payslips_done.filtered(lambda slip: slip.liquidar_por == "cesantias").sorted("date_from", reverse=True)
                if liquidaciones_cesantias:
                    payslip.date_from_cesantias = liquidaciones_cesantias[0].date_to + timedelta(days=1)
                else:
                    cut_year = payslip.contract_id.fecha_corte.year if payslip.contract_id.fecha_corte else payslip.date_to.year
                    payslip.date_from_cesantias = max(date(cut_year, 1, 1), contract_start)
            elif payslip.liquidar_por in ("cesantias", "intereses_cesantias"):
                payslip.date_from_cesantias = payslip.date_from
            elif payslip.liquidar_por == "prima":
                payslip.date_from_prima = payslip.date_from

            if payslip.date_from_cesantias and payslip.date_from_cesantias <= payslip.date_to:
                payslip.dias_intereses_cesantias = matematica.duracion360(payslip.date_from_cesantias, payslip.date_to)
                suspension_slips = payslip._l10n_co_payroll_get_previous_period_slips(
                    payslip.date_from_cesantias,
                    payslip.date_to,
                    ("nomina", "vacaciones"),
                )
                suspensiones = sum(suspension_slips.mapped("nod_unpaid_leaves"))
                payslip.dias_cesantias = max(payslip.dias_intereses_cesantias - suspensiones, 0.0)

    @api.depends("previous_payslips_done", "first_day_month", "last_day_month", "date_from")
    def _compute_l10n_co_payroll_month_progress(self):
        for payslip in self:
            payslip.dias_hecho = 0.0
            payslip.days_paid = 0.0
            payslip.dias_trabajados_mes_hecho = 0.0
            payslip.dias_a_pagar_hecho = 0.0
            payslip.nod_unpaid_leaves_hecho = 0.0
            payslip.dias_incapacidad_comun_hecho = 0.0
            payslip.dias_licencia_mat_pat_hecho = 0.0
            payslip.dias_vacaciones_hecho = 0.0
            payslip.valor_dia_reemplazo_hecho = 0.0

            if not payslip.first_day_month or not payslip.last_day_month or not payslip.date_from:
                continue

            previous_month_slips = payslip._l10n_co_payroll_get_previous_period_slips(
                payslip.first_day_month,
                payslip.last_day_month,
                ("nomina", "vacaciones"),
            ).filtered(lambda slip: slip.dias_a_pagar > 0)

            salary_amount = 0.0
            for previous_slip in previous_month_slips:
                if previous_slip.liquidar_por == "nomina":
                    payslip.dias_trabajados_mes_hecho += previous_slip.dias_trabajados
                    payslip.dias_a_pagar_hecho += previous_slip.dias_a_pagar
                    payslip.nod_unpaid_leaves_hecho += previous_slip.nod_unpaid_leaves
                    payslip.dias_incapacidad_comun_hecho += previous_slip.dias_incapacidad_comun
                    payslip.dias_licencia_mat_pat_hecho += previous_slip.dias_licencia_mat_pat
                    sum_ing_aux = sum(line.total for line in previous_slip.line_ids if line.code in ("ING_SAL", "AUX_TRA"))
                    sum_sal = sum(line.total for line in previous_slip.line_ids if line.code == "SUELDO")
                    if previous_slip.dias_a_pagar:
                        salary_amount += sum_ing_aux - previous_slip.nod_paid_leaves * sum_sal / previous_slip.dias_a_pagar
                else:
                    payslip.dias_vacaciones_hecho += previous_slip.dias_vacaciones
                payslip.dias_hecho += previous_slip.dias - (
                    previous_slip.dias_vacaciones if previous_slip.liquidar_por == "nomina" else 0.0
                )

            payslip.days_paid = payslip.dias_a_pagar_hecho
            if payslip.dias_trabajados_mes_hecho:
                payslip.valor_dia_reemplazo_hecho = round(salary_amount / payslip.dias_trabajados_mes_hecho, 2)

    @api.depends(
        "date_from",
        "date_to",
        "contract_id",
        "wage",
        "previous_payslips_done",
        "first_day_month",
        "dia_inicio_mes_anterior",
        "dia_fin_mes_anterior",
        "exempt_rent",
    )
    def _compute_l10n_co_payroll_reference_values(self):
        for payslip in self:
            base_wage = payslip.contract_id.wage or payslip.version_id.wage or payslip.wage or 0.0
            payslip.smlv = 0
            payslip.aux_trans = 0
            payslip.valor_uvt = 0
            payslip.valor_incapacidad_comun = 0.0
            payslip.valor_licencia_mat_pat = 0.0
            payslip.promedio_variable_sin_extras_ni_rdominicalf_360 = 0.0
            payslip.promedio_wage_360 = base_wage
            payslip.promedio_sal_aux_tras_360 = base_wage
            payslip.promedio_sal_aux_tras_180 = base_wage
            payslip.promedio_sal_aux_tras_90 = base_wage
            payslip.base_fondo_solidaridad_hecho = 0.0
            payslip.subsistence_fund_paid = 0.0
            payslip.solidarity_fund_paid = 0.0
            payslip.ibc_seguridad_social_mes_anterior = 0.0

            trace_variable = payslip._l10n_co_payroll_get_trace_variable() if payslip.date_from or payslip.date_to else False
            if trace_variable:
                payslip.smlv = trace_variable.smlv
                payslip.aux_trans = trace_variable.aux_trans
                payslip.valor_uvt = trace_variable.valor_uvt

            daily_wage = base_wage / 30
            payslip.valor_incapacidad_comun = round((payslip.dias_incapacidad_comun or 0.0) * daily_wage, 2)
            payslip.valor_licencia_mat_pat = round((payslip.dias_licencia_mat_pat or 0.0) * daily_wage, 2)

            transport_component = 0.0
            if payslip.contract_id.tipo_salario == "tradicional" and base_wage and payslip.smlv and base_wage < 2 * payslip.smlv:
                transport_component = payslip.aux_trans

            average_360 = payslip._l10n_co_payroll_get_variable_average(360)
            average_180 = payslip._l10n_co_payroll_get_variable_average(180)
            average_90 = payslip._l10n_co_payroll_get_variable_average(90)
            payslip.promedio_variable_sin_extras_ni_rdominicalf_360 = average_360
            payslip.promedio_wage_360 = round(base_wage + (average_360 * 30), 2)
            payslip.promedio_sal_aux_tras_360 = round(base_wage + transport_component + (average_360 * 30), 2)
            payslip.promedio_sal_aux_tras_180 = round(base_wage + transport_component + (average_180 * 30), 2)
            payslip.promedio_sal_aux_tras_90 = round(base_wage + transport_component + (average_90 * 30), 2)

            if payslip.liquidar_por in ("prima", "definitiva") and payslip.date_from_prima and payslip.date_to:
                prima_types = ("nomina", "vacaciones") if payslip.company_id.vacations_in_average else ("nomina",)
                nominas_prima = payslip.previous_payslips_done.filtered_domain(
                    [
                        ("liquidar_por", "in", prima_types),
                        ("date_from", ">=", payslip.date_from_prima),
                        ("date_to", "<=", payslip.date_to),
                    ]
                ).sorted("date_from")
                if nominas_prima:
                    promedio_180, _, _, _ = nominas_prima.calcular_promedio_variable(
                        payslip.contract_id,
                        payslip.date_from_prima,
                        payslip.date_to,
                        180,
                    )
                    payslip.promedio_sal_aux_tras_180 = round(promedio_180, 2)

            if payslip.liquidar_por in ("cesantias", "intereses_cesantias", "definitiva") and payslip.date_to:
                inicio_anio_periodo = date(year=payslip.date_to.year, month=1, day=1)
                fecha_inicio_90 = max(payslip.date_to + relativedelta(months=-3), inicio_anio_periodo)
                nominas_90 = self.env["hr.payslip"].search(
                    [
                        ("employee_id", "=", payslip.employee_id.id),
                        ("contract_id", "=", payslip.contract_id.id),
                        ("state", "in", ("done", "validated", "paid")),
                        ("liquidar_por", "in", ("nomina", "vacaciones")),
                        ("date_to", "<=", payslip.date_to),
                        ("date_from", ">=", fecha_inicio_90),
                    ],
                    order="date_from, date_to",
                )
                if nominas_90:
                    promedio_90, _, _, _ = nominas_90.calcular_promedio_variable(
                        payslip.contract_id,
                        fecha_inicio_90,
                        payslip.date_to,
                        90,
                    )
                    payslip.promedio_sal_aux_tras_90 = round(promedio_90, 2)

                if payslip.date_from_cesantias:
                    nominas_360 = self.env["hr.payslip"].search(
                        [
                            ("employee_id", "=", payslip.employee_id.id),
                            ("contract_id", "=", payslip.contract_id.id),
                            ("state", "in", ("done", "validated", "paid")),
                            ("liquidar_por", "in", ("nomina", "vacaciones")),
                            ("date_from", ">=", payslip.date_from_cesantias),
                            ("date_to", "<=", payslip.date_to),
                            ("date_from", ">=", inicio_anio_periodo),
                        ],
                        order="date_from, date_to",
                    )
                    if nominas_360:
                        promedio_360, _, _, _ = nominas_360.calcular_promedio_variable(
                            payslip.contract_id,
                            payslip.date_from_cesantias,
                            payslip.date_to,
                            360,
                        )
                        payslip.promedio_sal_aux_tras_360 = round(promedio_360, 2)

            if payslip.first_day_month and payslip.last_day_month:
                same_month_slips = payslip._l10n_co_payroll_get_previous_period_slips(
                    payslip.first_day_month,
                    payslip.last_day_month,
                    ("nomina", "vacaciones", "definitiva"),
                )
                for previous_slip in same_month_slips:
                    for line in previous_slip.line_ids:
                        if line.code == "BAS_FS":
                            payslip.base_fondo_solidaridad_hecho += line.total
                        elif line.code == "FON_SOL_SUB":
                            payslip.subsistence_fund_paid += line.total
                        elif line.code == "FON_SOL_SOL":
                            payslip.solidarity_fund_paid += line.total

            if payslip.dia_inicio_mes_anterior and payslip.dia_fin_mes_anterior:
                previous_month_slips = payslip.previous_payslips_done.filtered(
                    lambda slip: slip.date_from
                    and slip.date_to
                    and slip.date_from >= payslip.dia_inicio_mes_anterior
                    and slip.date_to <= payslip.dia_fin_mes_anterior
                )
                payslip.ibc_seguridad_social_mes_anterior = sum(
                    line.total
                    for slip in previous_month_slips
                    for line in slip.line_ids
                    if line.code == "BAS_SEG_SOC_AFP_EPS"
                )

    @api.depends("date_to", "exempt_rent", "previous_payslips_done")
    def _compute_l10n_co_payroll_exempt_rent_accumulated(self):
        for payslip in self:
            payslip.exempt_rent_accumulated = payslip.exempt_rent or 0.0
            if not payslip.date_to:
                continue
            first_day_year = date(payslip.date_to.year, 1, 1)
            previous_same_year = payslip.previous_payslips_done.filtered(
                lambda slip: slip.date_to and first_day_year <= slip.date_to <= payslip.date_to
            )
            payslip.exempt_rent_accumulated += sum(previous_same_year.mapped("exempt_rent"))

    def set_exempt_rent(self, exempt_rent, exempt_rent_accumulated):
        for payslip in self:
            payslip.exempt_rent = exempt_rent
            payslip.exempt_rent_accumulated = exempt_rent_accumulated
        return True

    def calculate_exempt_rent(self):
        for payslip in self:
            if not payslip.struct_id:
                raise ValidationError(
                    _(
                        "La nomina de %(employee)s no tiene estructura salarial configurada para calcular la renta exenta.",
                        employee=payslip.employee_id.name,
                    )
                )

            if not payslip.line_ids and payslip.state in ("validated", "paid"):
                raise ValidationError(
                    _(
                        "La nomina de %(employee)s no tiene lineas calculadas. Recalcula la nomina antes de calcular la renta exenta.",
                        employee=payslip.employee_id.name,
                    )
                )

            payslip.exempt_rent = 0.0
            # Keep the year-to-date base available before salary rules potentially overwrite it.
            payslip.exempt_rent_accumulated = sum(
                payslip.previous_payslips_done.filtered(
                    lambda slip: slip.date_to
                    and payslip.date_to
                    and slip.date_to.year == payslip.date_to.year
                    and slip.date_to <= payslip.date_to
                ).mapped("exempt_rent")
            )

            localdict = payslip._get_localdict()
            result_rules_dict = localdict["result_rules"]

            for rule in sorted(payslip.struct_id.rule_ids, key=lambda current_rule: current_rule.sequence):
                localdict.update(
                    {
                        "result": None,
                        "result_qty": 1.0,
                        "result_rate": 100,
                        "result_name": False,
                    }
                )
                if not rule._satisfy_condition(localdict):
                    continue

                if rule.code in localdict["same_type_input_lines"]:
                    for multi_line_rule in localdict["same_type_input_lines"][rule.code]:
                        localdict["inputs"][rule.code] = multi_line_rule
                        amount, qty, rate = rule._compute_rule(localdict)
                        tot_rule = payslip._get_payslip_line_total(amount, qty, rate, rule)
                        result_rules_dict[rule.code]["total"] += tot_rule
                        result_rules_dict[rule.code]["amount"] += tot_rule
                        result_rules_dict[rule.code]["quantity"] = 1
                        result_rules_dict[rule.code]["rate"] = 100
                        localdict = rule.category_id._sum_salary_rule_category(localdict, tot_rule)

                    input_line_ids = localdict["same_type_input_lines"][rule.code].ids
                    localdict["inputs"][rule.code] = self.__get_aggregator_hr_payslip_input_model()(
                        env=self.env, ids=input_line_ids, prefetch_ids=input_line_ids
                    )
                else:
                    amount, qty, rate = rule._compute_rule(localdict)
                    previous_amount = localdict.get(rule.code, 0.0)
                    tot_rule = payslip._get_payslip_line_total(amount, qty, rate, rule)
                    localdict[rule.code] = tot_rule
                    result_rules_dict[rule.code] = {
                        "total": tot_rule,
                        "amount": amount,
                        "quantity": qty,
                        "rate": rate,
                    }
                    localdict = rule.category_id._sum_salary_rule_category(localdict, tot_rule - previous_amount)

                if rule.code == "BAS_GRA_RTF":
                    break
        return False

    def action_calculate_exempt_rent(self):
        self.calculate_exempt_rent()
        return False

    def _l10n_co_payroll_normalize_sum_codes(self, values):
        if not values:
            return set()
        if isinstance(values, str):
            return {values}
        codes = set()
        try:
            iterator = iter(values)
        except TypeError:
            return codes
        for value in iterator:
            if isinstance(value, str):
                codes.add(value)
        return codes

    @api.model
    def sum(self, code_add, from_date, to_date=None, payslips=None, code_sub=None, payslip_types=None):
        if to_date is None:
            to_date = fields.Date.context_today(self)

        if payslips is None:
            payslips = self.previous_payslips_done if len(self) == 1 else self.env["hr.payslip"]

        if not payslips:
            payslips = self.env["hr.payslip"]

        code_add = self._l10n_co_payroll_normalize_sum_codes(code_add)
        code_sub = self._l10n_co_payroll_normalize_sum_codes(code_sub)
        if not code_add and not code_sub:
            return 0.0

        domain = [
            ("date_from", ">=", from_date),
            ("date_to", "<=", to_date),
        ]
        if payslip_types:
            domain.append(("liquidar_por", "in", payslip_types))

        payslips = payslips.filtered_domain(domain)
        result = 0.0
        for payslip in payslips:
            for line in payslip.line_ids:
                if line.code in code_add:
                    result += line.total if not payslip.credit_note else -line.total
                if code_sub and line.code in code_sub:
                    result -= line.total if not payslip.credit_note else -line.total
        return result

    def calcular_promedio_variable(self, contract_id, date_from, date_to, days=0):
        company = self[:1].company_id or contract_id.company_id or self.env.company
        variable_liquidado = 0.0
        ausencias_pagas_liquidadas = 0.0
        ausencias_nopagas_liquidadas = 0.0
        minima_fecha_nominas_liquidadas = False
        maxima_fecha_nominas_liquidadas = False
        dias_vacaciones_posteriores = 0.0
        maxima_fecha_vacaciones = False
        last_wage = contract_id.wage or 0.0
        reference_wage = contract_id.wage or 0.0
        no_licences_nr_in_bonus = company.licenses_as_suspension

        for nomina_liquidada in self.sorted("date_from"):
            ing_sal = sum(line.total for line in nomina_liquidada.line_ids if line.code == "ING_SAL")
            aux_tra = sum(line.total for line in nomina_liquidada.line_ids if line.code == "AUX_TRA")
            aux_tra_value = 0.0

            if days == 180 and aux_tra > 0:
                if nomina_liquidada.contract_id.salario_variable:
                    if nomina_liquidada.company_id.all_aux_tra_in_average_variable_salary:
                        aux_tra_value = (
                            nomina_liquidada.nod_paid_leaves
                            + nomina_liquidada.dias_incapacidad_comun
                            + nomina_liquidada.dias_trabajados
                            + nomina_liquidada.dias_vacaciones
                            + nomina_liquidada.dias_licencia_mat_pat
                        ) * (nomina_liquidada.aux_trans / 30)
                    else:
                        aux_tra_value = aux_tra
                elif nomina_liquidada.company_id.all_aux_tra_in_average_fixed_salary:
                    aux_tra_value = (
                        nomina_liquidada.nod_paid_leaves
                        + nomina_liquidada.dias_incapacidad_comun
                        + nomina_liquidada.dias_trabajados
                        + nomina_liquidada.dias_vacaciones
                        + nomina_liquidada.dias_licencia_mat_pat
                    ) * (nomina_liquidada.aux_trans / 30)
                else:
                    aux_tra_value = aux_tra
            elif days == 360 and aux_tra > 0:
                if nomina_liquidada.contract_id.salario_variable:
                    if nomina_liquidada.company_id.all_aux_tra_in_severance_variable_salary:
                        aux_tra_value = (
                            nomina_liquidada.nod_paid_leaves
                            + nomina_liquidada.dias_incapacidad_comun
                            + nomina_liquidada.dias_trabajados
                            + nomina_liquidada.dias_vacaciones
                            + nomina_liquidada.dias_licencia_mat_pat
                        ) * (nomina_liquidada.aux_trans / 30)
                    else:
                        aux_tra_value = aux_tra
                elif nomina_liquidada.company_id.all_aux_tra_in_severance_fixed_salary:
                    aux_tra_value = (
                        nomina_liquidada.nod_paid_leaves
                        + nomina_liquidada.dias_incapacidad_comun
                        + nomina_liquidada.dias_trabajados
                        + nomina_liquidada.dias_vacaciones
                        + nomina_liquidada.dias_licencia_mat_pat
                    ) * (nomina_liquidada.aux_trans / 30)
                else:
                    aux_tra_value = aux_tra
            else:
                aux_tra_value = aux_tra

            inc_com = 0.0
            if nomina_liquidada.dias_incapacidad_comun > 0:
                if nomina_liquidada.contract_id.salario_variable:
                    if nomina_liquidada.company_id.disability_one_hundred_average_variable_salary and days == 180:
                        inc_com = nomina_liquidada.dias_incapacidad_comun * ((nomina_liquidada.wage or 0.0) / 30)
                    else:
                        inc_com = sum(
                            line.total for line in nomina_liquidada.line_ids if line.code == "INCAPACIDAD_COMUN"
                        )
                elif nomina_liquidada.company_id.disability_one_hundred_average_fixed_salary and days == 180:
                    inc_com = nomina_liquidada.dias_incapacidad_comun * ((nomina_liquidada.wage or 0.0) / 30)
                else:
                    inc_com = sum(line.total for line in nomina_liquidada.line_ids if line.code == "INCAPACIDAD_COMUN")

            val_vacations = 0.0
            if not company.vacations_in_average and days == 180 and nomina_liquidada.dias_vacaciones:
                val_vacations = ((nomina_liquidada.wage or 0.0) / 30) * nomina_liquidada.dias_vacaciones

            variable_liquidado += ing_sal + val_vacations + aux_tra_value + inc_com
            ausencias_pagas_liquidadas += (
                nomina_liquidada.nod_paid_leaves
                + nomina_liquidada.dias_incapacidad_comun
                + nomina_liquidada.dias_licencia_mat_pat
                + (nomina_liquidada.dias_vacaciones if nomina_liquidada.liquidar_por != "vacaciones" else 0.0)
            )

            if (no_licences_nr_in_bonus and days == 180) or days != 180:
                ausencias_nopagas_liquidadas += nomina_liquidada.nod_unpaid_leaves
            ausencias_nopagas_liquidada = nomina_liquidada.nod_unpaid_leaves if days != 90 else 0.0
            if ausencias_nopagas_liquidada > 0:
                variable_liquidado += ausencias_nopagas_liquidada * ((nomina_liquidada.wage or 0.0) / 30)

            if nomina_liquidada.liquidar_por != "vacaciones":
                minima_fecha_nominas_liquidadas = (
                    min(minima_fecha_nominas_liquidadas, nomina_liquidada.date_from)
                    if minima_fecha_nominas_liquidadas
                    else nomina_liquidada.date_from
                )
                maxima_fecha_nominas_liquidadas = (
                    max(maxima_fecha_nominas_liquidadas, nomina_liquidada.date_to)
                    if maxima_fecha_nominas_liquidadas
                    else nomina_liquidada.date_to
                )
                if maxima_fecha_nominas_liquidadas == nomina_liquidada.date_to:
                    last_wage = (nomina_liquidada.wage or 0.0) + aux_tra
                    reference_wage = nomina_liquidada.wage or 0.0
            else:
                maxima_fecha_vacaciones = nomina_liquidada.date_to

        salarios_previos = contract_id.traza_atributo_salario_ids.filtered(
            lambda salario: salario.fecha_actualizacion >= date_from
            and (
                not minima_fecha_nominas_liquidadas
                or salario.fecha_actualizacion < minima_fecha_nominas_liquidadas
            )
        )

        variable_saldo = 0.0
        ausencias_pagas_saldo = 0.0
        ausencias_nopagas_saldo = 0.0
        if contract_id.traza_atributo_salario_ids and salarios_previos:
            for salario in salarios_previos:
                variable_saldo += salario.valor + salario.valor_auxilio_transporte_conectividad
                ausencias_pagas_saldo += salario.dias_ausencias_pagas
                if (no_licences_nr_in_bonus and days == 180) or days != 180:
                    ausencias_nopagas_saldo += salario.dias_suspensiones
                ausencias_nopaga_saldo = salario.dias_suspensiones if days != 90 else 0.0
                if ausencias_nopaga_saldo > 0:
                    variable_saldo += ausencias_nopaga_saldo * (reference_wage / 30)
                minima_fecha_nominas_liquidadas = (
                    min(minima_fecha_nominas_liquidadas, salario.fecha_actualizacion)
                    if minima_fecha_nominas_liquidadas
                    else salario.fecha_actualizacion
                )
                maxima_fecha_nominas_liquidadas = (
                    max(maxima_fecha_nominas_liquidadas, contract_id.fecha_corte)
                    if maxima_fecha_nominas_liquidadas
                    else contract_id.fecha_corte
                )
            if not (contract_id.fecha_corte or maxima_fecha_nominas_liquidadas):
                raise ValidationError(_("Si tiene registrados los salarios del sistema anterior, debe tener una fecha de corte."))

        if maxima_fecha_vacaciones and (
            not maxima_fecha_nominas_liquidadas or maxima_fecha_vacaciones > maxima_fecha_nominas_liquidadas
        ):
            nomina_vacaciones = self.env["hr.payslip"].search(
                [
                    ("employee_id", "=", contract_id.employee_id.id),
                    ("contract_id", "=", contract_id.id),
                    ("liquidar_por", "=", "vacaciones"),
                    ("date_to", "=", maxima_fecha_vacaciones),
                    ("state", "in", ("done", "validated", "paid")),
                ],
                order="date_to desc",
                limit=1,
            )
            dias_vacaciones_posteriores = nomina_vacaciones.dias_a_pagar

        dias_total = (
            matematica.duracion360(minima_fecha_nominas_liquidadas, maxima_fecha_nominas_liquidadas)
            if minima_fecha_nominas_liquidadas
            and maxima_fecha_nominas_liquidadas
            and minima_fecha_nominas_liquidadas <= maxima_fecha_nominas_liquidadas
            else 0.0
        ) + dias_vacaciones_posteriores
        dias_pagos = dias_total - (ausencias_nopagas_liquidadas + ausencias_nopagas_saldo)
        dias_dividir = dias_total - (
            ausencias_pagas_liquidadas
            + ausencias_nopagas_liquidadas
            + ausencias_pagas_saldo
            + ausencias_nopagas_saldo
        )

        if days in (180, 360, 90):
            if contract_id.salario_variable or company.average_in_fixed_salary:
                promedio_variable = ((variable_liquidado + variable_saldo) * 30 / dias_pagos) if dias_pagos else 0.0
            else:
                promedio_variable = last_wage
        else:
            promedio_variable = (
                ((variable_liquidado + variable_saldo) * dias_pagos * 30) / (dias_dividir * dias_total)
                if dias_dividir and dias_total
                else 0.0
            )
        return (
            promedio_variable,
            ausencias_nopagas_liquidadas + ausencias_nopagas_saldo,
            variable_liquidado + variable_saldo,
            dias_pagos,
        )

    def duracion360(self, date_from, date_to):
        self.ensure_one()
        return matematica.duracion360(date_from, date_to)

    def payroll_vacation_days(self, employee_id, date_from, date_to):
        self.ensure_one()
        employee_id = getattr(employee_id, "id", employee_id)
        vacations = self.env["hr.payslip"].search(
            [
                ("employee_id", "=", employee_id),
                "|",
                "|",
                "&",
                ("date_from", ">=", date_from),
                ("date_from", "<=", date_to),
                "&",
                ("date_to", ">=", date_from),
                ("date_to", "<=", date_to),
                "&",
                ("date_from", "<=", date_from),
                ("date_to", ">=", date_to),
                ("liquidar_por", "=", "vacaciones"),
                ("state", "in", ("done", "validated", "paid")),
            ]
        )
        value_days = 0.0
        for vacation in vacations:
            for vacation_line in vacation.line_ids:
                if vacation_line.code != "ING_SAL":
                    continue
                if vacation.date_from >= date_from and vacation.date_to <= date_to:
                    value_days += vacation_line.amount
                    continue

                total_days = (vacation.date_to - vacation.date_from).days + 1
                if not total_days:
                    continue
                if vacation.date_from < date_from and vacation.date_to < date_to:
                    days = (vacation.date_to - date_from).days + 1
                elif vacation.date_to > date_to and vacation.date_from > date_from:
                    days = (date_to - vacation.date_from).days + 1
                else:
                    days = (date_to - date_from).days + 1
                value_days += (vacation_line.amount / total_days) * days
        return value_days

    def get_nod_paid_leaves(self, employee_id, date_from, date_to):
        self.ensure_one()
        employee_id = getattr(employee_id, "id", employee_id)
        nominas = self.previous_payslips_done.filtered_domain(
            [
                ("employee_id", "=", employee_id),
                ("date_from", ">=", date_from),
                ("date_to", "<=", date_to),
                ("liquidar_por", "=", "nomina"),
            ]
        )
        return sum(nominas.mapped("nod_paid_leaves"))

    @api.model
    def get_days_worked(self, employee_id, date_from, date_to, previous_payslips_done=False):
        payslips = previous_payslips_done
        if not payslips and len(self) == 1:
            payslips = self.previous_payslips_done
        if not payslips:
            payslips = self.env["hr.payslip"]
        nominas = payslips.filtered(
            lambda slip: slip.date_from >= date_from
            and slip.date_to <= date_to
            and slip.liquidar_por in ("nomina", "vacaciones")
        )
        days_worked = 0.0
        for nomina in nominas:
            if nomina.liquidar_por == "nomina":
                days_worked += nomina.dias - nomina.nod_unpaid_leaves - nomina.dias_vacaciones
            else:
                days_worked += nomina.dias_vacaciones
        return days_worked

    def _validate_date(self):
        for payslip in self:
            if not payslip.employee_id or not payslip.contract_id:
                continue
            payslips_done = self.search(
                [
                    ("employee_id", "=", payslip.employee_id.id),
                    ("contract_id", "=", payslip.contract_id.id),
                    ("state", "in", ("done", "validated", "paid")),
                    ("liquidar_por", "=", payslip.liquidar_por),
                    ("id", "!=", payslip._origin.id or payslip.id),
                    "|",
                    "|",
                    "&",
                    ("date_from", ">=", payslip.date_from),
                    ("date_from", "<=", payslip.date_to),
                    "&",
                    ("date_to", ">=", payslip.date_from),
                    ("date_to", "<=", payslip.date_to),
                    "&",
                    ("date_from", "<=", payslip.date_from),
                    ("date_to", ">=", payslip.date_to),
                ]
            )
            if payslips_done:
                payslip.warning_message = _(
                    "Ya existe liquidacion de %(liquidation)s dentro del periodo seleccionado para %(employee)s.",
                    liquidation=payslip.liquidar_por,
                    employee=payslip.employee_id.name,
                )
                return False
            payslip.warning_message = False
        return True

    def change_name(self):
        for payslip in self:
            if payslip.employee_id and payslip.date_from and payslip.date_to:
                payslip.name = _(
                    "Liquidacion %(liquidation)s de %(employee)s - %(date_from)s a %(date_to)s",
                    liquidation=payslip.liquidar_por,
                    employee=payslip.employee_id.name,
                    date_from=payslip.date_from,
                    date_to=payslip.date_to,
                )
            else:
                payslip.name = False

    @api.onchange("liquidar_por", "employee_id", "date_from", "date_to")
    def _onchange_struct_id_co(self):
        for payslip in self:
            payslip.change_name()
            payslip._validate_date()

    @api.onchange("liquidar_por", "dias_vacaciones_compensadas")
    def _onchange_liquidar_por(self):
        for payslip in self:
            if not payslip.dias_vacaciones_compensadas or payslip.liquidar_por == "definitiva":
                continue
            if payslip.dias_vacaciones_compensadas > 7:
                raise ValidationError(_("Se podran pagar maximo 7 dias por periodo como vacaciones compensadas."))
            if not payslip.employee_id or not payslip.contract_id or not payslip.date_to:
                continue

            allocation = self.env["hr.leave.allocation"].search(
                [
                    ("employee_id", "=", payslip.employee_id.id),
                    ("contract_id", "=", payslip.contract_id.id),
                    ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
                    ("state", "=", "validate"),
                ],
                limit=1,
            )
            if not allocation:
                continue
            if allocation.anticipated_vacations > 0:
                raise ValidationError(
                    _(
                        "El empleado %(employee)s tiene dias de vacaciones adelantados sin recuperar.",
                        employee=payslip.employee_id.name,
                    )
                )

            contract_start = payslip.contract_id._l10n_co_payroll_get_start_date()
            if contract_start and contract_start > (payslip.date_to - relativedelta(months=9)):
                raise ValidationError(
                    _(
                        "El empleado %(employee)s tiene menos de nueve meses de antiguedad.",
                        employee=payslip.employee_id.name,
                    )
                )

            remaining_days = floor(allocation.remaining_days().get(allocation.employee_id.id, 0.0))
            if payslip.dias_vacaciones_compensadas > remaining_days:
                payslip.dias_vacaciones_compensadas = remaining_days
                return {
                    "warning": {
                        "title": _("Valor invalido"),
                        "message": _(
                            "%(employee)s dispone de %(days)s dias para vacaciones compensadas.",
                            employee=payslip.employee_id.name,
                            days=remaining_days,
                        ),
                    }
                }

            book_vacations = self.env["book.vacations"].search(
                [
                    ("employee_id", "=", payslip.employee_id.id),
                    ("contract_id", "=", payslip.contract_id.id),
                ],
                limit=1,
            )
            if book_vacations and (
                payslip.dias_vacaciones_compensadas + book_vacations.compensated_vacations
            ) > (allocation.number_of_days / 2):
                raise ValidationError(
                    _("Las vacaciones compensadas totales superan la mitad del acumulado de vacaciones.")
                )

    @api.depends(
        "employee_id",
        "employee_id.eps_id",
        "employee_id.fp_id",
        "employee_id.fc_id",
        "employee_id.ccf_id",
        "contract_id",
        "struct_id",
        "struct_id.journal_payment_id",
        "struct_id.journal_third_payment_id",
        "company_id.ccf_id",
        "company_id.arl_id",
        "company_id.icbf_id",
        "company_id.sena_id",
        "company_id.dian_id",
        "date_from",
        "date_to",
        "liquidar_por",
        "line_ids.total",
        "line_ids.salary_rule_id",
        "line_ids.salary_rule_id.partner_id",
    )
    def _compute_l10n_co_payroll_warning_message(self):
        for payslip in self:
            messages = []
            if payslip.date_from and payslip.date_to:
                current_month_end = date_utils.end_of(fields.Date.context_today(payslip), "month")
                if payslip.date_to > current_month_end:
                    next_available_day = date_utils.add(current_month_end, days=1)
                    messages.append(
                        _(
                            "Esta nomina puede ser incorrecta. Las entradas de trabajo posteriores a %(date)s pueden no existir todavia.",
                            date=next_available_day,
                        )
                    )
            if payslip.employee_id and payslip.contract_id and payslip.date_from and payslip.date_to:
                duplicate = self.search(
                    [
                        ("id", "!=", payslip.id or payslip._origin.id or 0),
                        ("employee_id", "=", payslip.employee_id.id),
                        ("contract_id", "=", payslip.contract_id.id),
                        ("liquidar_por", "=", payslip.liquidar_por),
                        ("state", "in", ("draft", "validated", "paid")),
                        "|",
                        "|",
                        "&",
                        ("date_from", ">=", payslip.date_from),
                        ("date_from", "<=", payslip.date_to),
                        "&",
                        ("date_to", ">=", payslip.date_from),
                        ("date_to", "<=", payslip.date_to),
                        "&",
                        ("date_from", "<=", payslip.date_from),
                        ("date_to", ">=", payslip.date_to),
                    ],
                    limit=1,
                )
                if duplicate:
                    messages.append(
                        _(
                            "Ya existe una liquidacion de %(liquidation)s dentro del periodo seleccionado para %(employee)s.",
                            liquidation=payslip.liquidar_por,
                            employee=payslip.employee_id.name,
                        )
                    )
            messages.extend(payslip._l10n_co_payroll_get_related_move_warning_messages())
            payslip.warning_message = " ".join(dict.fromkeys(messages)) if messages else False

    @api.depends(
        "date_from",
        "date_to",
        "liquidar_por",
        "date_from_prima",
        "nod_paid_leaves",
        "nod_unpaid_leaves",
        "dias_incapacidad_comun",
        "dias_licencia_mat_pat",
    )
    def _compute_l10n_co_payroll_days(self):
        for payslip in self:
            if payslip.date_from and payslip.date_to and payslip.date_to >= payslip.date_from:
                period_days = (payslip.date_to - payslip.date_from).days + 1
                payslip.days_month_date_from = calendar.monthrange(payslip.date_from.year, payslip.date_from.month)[1]
            else:
                period_days = 0
                payslip.days_month_date_from = 0

            if payslip.liquidar_por == "vacaciones":
                payslip.dias_vacaciones = period_days
                payslip.dias_a_pagar = period_days
                payslip.dias_trabajados = 0
            else:
                payslip.dias_vacaciones = 0
                payslip.dias_a_pagar = max(
                    period_days - payslip.nod_unpaid_leaves - payslip.dias_incapacidad_comun - payslip.dias_licencia_mat_pat,
                    0,
                )
                payslip.dias_trabajados = max(payslip.dias_a_pagar - payslip.nod_paid_leaves, 0)
            if (
                payslip.liquidar_por in ("prima", "definitiva")
                and payslip.date_from_prima
                and payslip.date_to
                and payslip.date_from_prima <= payslip.date_to
            ):
                payslip.dias_prima = matematica.duracion360(payslip.date_from_prima, payslip.date_to)
            else:
                payslip.dias_prima = period_days if payslip.liquidar_por == "prima" else 0

    @api.depends("version_id.salario_variable")
    def _compute_l10n_co_payroll_salary_variation(self):
        for payslip in self:
            payslip.tipo_variacion_salario = "variable" if payslip.version_id.salario_variable else "fijo"

    def _l10n_co_payroll_get_payment_date(self):
        self.ensure_one()
        return self.move_id_pago.date or self.paid_date or self.date_to

    def _l10n_co_payroll_get_payment_move_date(self):
        self.ensure_one()
        return self.date or fields.Date.end_of(self.date_to, "month")

    def _l10n_co_payroll_get_payment_partner(self):
        self.ensure_one()
        return self.employee_id._l10n_co_payroll_get_home_partner() or self.employee_id.work_contact_id

    def _l10n_co_payroll_get_payment_benefit_account(self, payment_journal, line):
        self.ensure_one()
        account_by_code = {
            "CES": payment_journal.severance_account_id,
            "INT_CES": payment_journal.severance_interest_account_id,
            "PRI_SER": payment_journal.service_bonus_account_id,
            "VAC": payment_journal.vacations_account_id,
            "VACACIONES_COMPENSADAS": payment_journal.vacations_account_id,
        }
        return account_by_code.get(line.code)

    def _l10n_co_payroll_get_payment_benefit_move_lines(self, payment_journal, move_date, partner):
        self.ensure_one()
        benefit_lines = []
        benefit_total = 0.0
        benefit_codes = {"CES", "INT_CES", "PRI_SER", "VAC", "VACACIONES_COMPENSADAS"}

        for line in self.line_ids.filtered(lambda current: current.code in benefit_codes and current.category_id):
            amount = self._l10n_co_payroll_get_payment_net_amount(line)
            if self.company_id.currency_id.is_zero(amount):
                continue

            account = self._l10n_co_payroll_get_payment_benefit_account(payment_journal, line)
            if not account:
                raise ValidationError(
                    _(
                        "El diario de pagos %(journal)s no tiene cuenta configurada para %(rule)s.",
                        journal=payment_journal.display_name,
                        rule=line.name or line.code,
                    )
                )

            benefit_total += amount
            benefit_lines.append(
                (
                    0,
                    0,
                    {
                        "name": _("%(name)s - (%(employee)s)", name=line.name or line.code, employee=self.employee_id.name),
                        "partner_id": partner.id if partner else False,
                        "account_id": account.id,
                        "journal_id": payment_journal.id,
                        "date": move_date,
                        "employee_id": self.employee_id.id,
                        "debit": amount if amount > 0 else 0.0,
                        "credit": -amount if amount < 0 else 0.0,
                    },
                )
            )

        return benefit_lines, benefit_total

    def _l10n_co_payroll_get_payment_net_line(self):
        self.ensure_one()
        return self.line_ids.filtered(lambda line: line.code == "NET")[:1]

    def _l10n_co_payroll_get_payment_counterpart_account(self, net_line):
        self.ensure_one()
        rule_account = self.env["salary.rule.account"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("regla_salarial", "=", net_line.salary_rule_id.id),
                ("area_trabajo", "=", self.contract_id.area_trabajo),
            ],
            limit=1,
        )
        return (
            rule_account.account_credit
            or net_line.salary_rule_id.account_credit
            or self.struct_id.account_receivable_employee_id
        )

    def _l10n_co_payroll_has_third_payment_candidates(self):
        self.ensure_one()
        return bool(self._l10n_co_payroll_get_third_payment_candidate_lines())

    def _l10n_co_payroll_get_third_payment_candidate_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: (
                line.category_id
                and line.salary_rule_id.origin_partner
                and line.salary_rule_id.origin_partner != "employee"
                and not self.company_id.currency_id.is_zero(-line.total if self.credit_note else line.total)
            )
        )

    def _l10n_co_payroll_can_create_payment_move(self):
        self.ensure_one()
        payment_journal = self.struct_id.journal_payment_id
        if not payment_journal or not payment_journal.default_account_id:
            return False

        net_line = self._l10n_co_payroll_get_payment_net_line()
        if not net_line:
            return False

        amount = self._l10n_co_payroll_get_payment_net_amount(net_line)
        if self.company_id.currency_id.is_zero(amount):
            return False

        return bool(self._l10n_co_payroll_get_payment_counterpart_account(net_line))

    def _l10n_co_payroll_can_create_third_payment_move(self):
        self.ensure_one()
        if not self._l10n_co_payroll_has_third_payment_candidates():
            return False

        third_payment_journal = self.struct_id.journal_third_payment_id
        if not third_payment_journal or not third_payment_journal.default_account_id:
            return False
        return True

    def _l10n_co_payroll_get_related_move_warning_messages(self):
        self.ensure_one()
        if not self.struct_id:
            return []

        messages = []
        payment_journal = self.struct_id.journal_payment_id
        if not payment_journal:
            messages.append(
                _(
                    "La estructura %(structure)s no tiene diario de pagos configurado.",
                    structure=self.struct_id.display_name,
                )
            )
        else:
            if not payment_journal.default_account_id:
                messages.append(
                    _(
                        "El diario de pagos %(journal)s no tiene cuenta por defecto configurada.",
                        journal=payment_journal.display_name,
                    )
                )
            net_line = self._l10n_co_payroll_get_payment_net_line()
            if net_line:
                net_amount = self._l10n_co_payroll_get_payment_net_amount(net_line)
                if not self.company_id.currency_id.is_zero(net_amount) and not self._l10n_co_payroll_get_payment_counterpart_account(net_line):
                    messages.append(
                        _(
                            "La estructura %(structure)s no tiene cuenta por cobrar del empleado y la linea NET de %(employee)s no tiene cuenta contable para el asiento de pago.",
                            structure=self.struct_id.display_name,
                            employee=self.employee_id.name,
                        )
                    )

        if self._l10n_co_payroll_has_third_payment_candidates():
            third_payment_journal = self.struct_id.journal_third_payment_id
            if not third_payment_journal:
                messages.append(
                    _(
                        "La estructura %(structure)s no tiene diario de pagos a terceros configurado.",
                        structure=self.struct_id.display_name,
                    )
                )
            elif not third_payment_journal.default_account_id:
                messages.append(
                    _(
                        "El diario de terceros %(journal)s no tiene cuenta por defecto configurada.",
                        journal=third_payment_journal.display_name,
                    )
                )
            messages.extend(self._l10n_co_payroll_get_third_payment_warning_messages())

        return messages

    def _l10n_co_payroll_get_payment_net_amount(self, net_line):
        self.ensure_one()
        return -net_line.total if self.credit_note else net_line.total

    def _l10n_co_payroll_get_reference_label(self):
        self.ensure_one()
        return getattr(self, "name", False) or self.employee_id.name

    def _l10n_co_payroll_get_third_payment_journal(self):
        self.ensure_one()
        third_payment_journal = self.struct_id.journal_third_payment_id
        if not third_payment_journal:
            raise ValidationError(
                _(
                    "La estructura %(structure)s no tiene diario de pagos a terceros configurado.",
                    structure=self.struct_id.display_name,
                )
            )
        if not third_payment_journal.default_account_id:
            raise ValidationError(
                _(
                    "El diario de terceros %(journal)s no tiene cuenta por defecto configurada.",
                    journal=third_payment_journal.display_name,
                )
            )
        return third_payment_journal

    def _l10n_co_payroll_get_third_partner(self, line):
        self.ensure_one()
        employee = self.employee_id
        company = self.company_id
        partner_by_origin = {
            "eps": employee.eps_id,
            "fp": employee.fp_id,
            "fc": employee.fc_id,
            "ccf": employee.ccf_id or company.ccf_id,
            "arl": company.arl_id,
            "icbf": company.icbf_id,
            "sena": company.sena_id,
            "dian": company.dian_id,
            "rule": line.salary_rule_id.partner_id,
        }
        return partner_by_origin.get(line.salary_rule_id.origin_partner)

    def _l10n_co_payroll_get_third_payment_warning_messages(self):
        self.ensure_one()
        messages = []
        candidate_lines = self._l10n_co_payroll_get_third_payment_candidate_lines()
        if not candidate_lines:
            return messages

        employee = self.employee_id
        company = self.company_id
        origin_requirements = [
            ("eps", employee.eps_id, _("la afiliacion EPS del empleado")),
            ("fp", employee.fp_id, _("la afiliacion a fondo de pensiones del empleado")),
            ("fc", employee.fc_id, _("la afiliacion a fondo de cesantias del empleado")),
            ("ccf", employee.ccf_id or company.ccf_id, _("la afiliacion/contacto de caja de compensacion")),
            ("arl", company.arl_id, _("el contacto ARL de la compania")),
            ("icbf", company.icbf_id, _("el contacto ICBF de la compania")),
            ("sena", company.sena_id, _("el contacto SENA de la compania")),
            ("dian", company.dian_id, _("el contacto DIAN de la compania")),
        ]

        for origin, resolved_partner, label in origin_requirements:
            if not resolved_partner and candidate_lines.filtered(lambda line, current_origin=origin: line.salary_rule_id.origin_partner == current_origin):
                messages.append(
                    _(
                        "La nomina de %(employee)s no puede generar el asiento a terceros porque falta %(label)s.",
                        employee=self.employee_id.name,
                        label=label,
                    )
                )

        for line in candidate_lines:
            if line.salary_rule_id.origin_partner == "rule" and not line.salary_rule_id.partner_id:
                messages.append(
                    _(
                        "La regla %(rule)s no tiene tercero configurado para el asiento a terceros de %(employee)s.",
                        rule=line.salary_rule_id.name,
                        employee=self.employee_id.name,
                    )
                )

            amount = -line.total if self.credit_note else line.total
            if not self._l10n_co_payroll_get_third_payment_account(line, amount):
                messages.append(
                    _(
                        "La regla %(rule)s no tiene cuenta contable para el asiento a terceros de %(employee)s.",
                        rule=line.salary_rule_id.name,
                        employee=self.employee_id.name,
                    )
                )

        return list(dict.fromkeys(messages))

    def _l10n_co_payroll_get_contract_entry_override_allocations(self, line, amount):
        self.ensure_one()
        if not line.salary_rule_id.code:
            return []

        input_lines = self.input_line_ids.filtered(
            lambda input_line: input_line.from_contract
            and input_line.new_entry_ids
            and input_line.input_type_id
            and input_line.input_type_id.code == line.salary_rule_id.code
        )
        if not input_lines:
            return []

        contract_entries = self.env["new.entry"]
        for input_line in input_lines:
            entry_ids = [int(entry_id) for entry_id in (input_line.new_entry_ids or "").split(",") if entry_id.isdigit()]
            contract_entries |= self.env["new.entry"].browse(entry_ids).exists()

        contract_entries = contract_entries.filtered(lambda entry: entry.partner_id or entry.account_id)
        if not contract_entries:
            return []

        invalid_entries = contract_entries.filtered(lambda entry: entry.partner_id and not entry.account_id)
        if invalid_entries:
            raise ValidationError(
                _(
                    "La novedad %(entry)s del empleado %(employee)s tiene tercero pero no cuenta contable.",
                    entry=invalid_entries[0].display_name,
                    employee=self.employee_id.name,
                )
            )

        allocations = []
        total_override_amount = 0.0
        for contract_entry in contract_entries:
            entry_amount = self._l10n_co_payroll_get_contract_entry_amount(contract_entry)
            if entry_amount <= 0:
                continue
            allocations.append((contract_entry, entry_amount))
            total_override_amount += entry_amount

        if not allocations or self.company_id.currency_id.is_zero(total_override_amount):
            return []

        total_line_amount = abs(amount)
        if self.company_id.currency_id.is_zero(total_line_amount):
            return []

        target_override_total = min(total_line_amount, total_override_amount)
        scale = min(1.0, total_line_amount / total_override_amount)
        signed_allocations = []
        consumed_amount = 0.0
        sign = 1 if amount >= 0 else -1
        for index, (contract_entry, entry_amount) in enumerate(allocations, start=1):
            if index == len(allocations):
                allocation_abs = round(max(target_override_total - consumed_amount, 0.0), 2)
            else:
                allocation_abs = round(entry_amount * scale, 2)
                consumed_amount += allocation_abs
            if self.company_id.currency_id.is_zero(allocation_abs):
                continue
            signed_allocations.append((contract_entry, sign * allocation_abs))

        return signed_allocations

    def _l10n_co_payroll_get_third_payment_account(self, line, amount):
        self.ensure_one()
        rule_account = self.env["salary.rule.account"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("regla_salarial", "=", line.salary_rule_id.id),
                ("area_trabajo", "=", self.contract_id.area_trabajo),
            ],
            limit=1,
        )
        if amount > 0:
            return rule_account.account_credit or line.salary_rule_id.account_credit
        return rule_account.account_debit or line.salary_rule_id.account_debit

    def _l10n_co_payroll_prepare_third_payment_move_vals(self):
        self.ensure_one()
        third_payment_journal = self._l10n_co_payroll_get_third_payment_journal()
        move_date = self._l10n_co_payroll_get_payment_move_date()
        reference_label = self._l10n_co_payroll_get_reference_label()
        aggregated_lines = {}

        for line in self.line_ids.filtered(lambda line: line.category_id and line.salary_rule_id.origin_partner and line.salary_rule_id.origin_partner != "employee"):
            amount = -line.total if self.credit_note else line.total
            if self.company_id.currency_id.is_zero(amount):
                continue

            allocations = []
            allocated_amount = 0.0
            for contract_entry, contract_amount in self._l10n_co_payroll_get_contract_entry_override_allocations(line, amount):
                partner = contract_entry.partner_id or self._l10n_co_payroll_get_third_partner(line)
                if not partner:
                    raise ValidationError(
                        _(
                            "La novedad %(entry)s no tiene tercero resuelto para %(employee)s.",
                            entry=contract_entry.display_name,
                            employee=self.employee_id.name,
                        )
                    )
                account = contract_entry.account_id or self._l10n_co_payroll_get_third_payment_account(line, contract_amount)
                if not account:
                    raise ValidationError(
                        _(
                            "La novedad %(entry)s no tiene cuenta contable para el asiento de terceros de %(employee)s.",
                            entry=contract_entry.display_name,
                            employee=self.employee_id.name,
                        )
                    )
                allocations.append(
                    {
                        "partner": partner,
                        "account": account,
                        "amount": contract_amount,
                        "label": _("%(entry)s - (%(employee)s)", entry=contract_entry.description or line.salary_rule_id.name, employee=self.employee_id.name),
                    }
                )
                allocated_amount += contract_amount

            remaining_amount = amount - allocated_amount
            if not self.company_id.currency_id.is_zero(remaining_amount):
                partner = self._l10n_co_payroll_get_third_partner(line)
                if not partner:
                    raise ValidationError(
                        _(
                            "La regla %(rule)s no tiene tercero resuelto para %(employee)s.",
                            rule=line.salary_rule_id.name,
                            employee=self.employee_id.name,
                        )
                    )

                account = self._l10n_co_payroll_get_third_payment_account(line, remaining_amount)
                if not account:
                    raise ValidationError(
                        _(
                            "La regla %(rule)s no tiene cuenta contable para el asiento de terceros de %(employee)s.",
                            rule=line.salary_rule_id.name,
                            employee=self.employee_id.name,
                        )
                    )
                allocations.append(
                    {
                        "partner": partner,
                        "account": account,
                        "amount": remaining_amount,
                        "label": _("%(rule)s - (%(employee)s)", rule=line.salary_rule_id.name, employee=self.employee_id.name),
                    }
                )

            for allocation in allocations:
                allocation_amount = allocation["amount"]
                debit = allocation_amount if allocation_amount > 0 else 0.0
                credit = -allocation_amount if allocation_amount < 0 else 0.0
                key = (
                    allocation["partner"].id,
                    allocation["account"].id,
                    line.salary_rule_id.id,
                    allocation["label"],
                )
                aggregated_line = aggregated_lines.setdefault(
                    key,
                    {
                        "name": allocation["label"],
                        "partner_id": allocation["partner"].id,
                        "account_id": allocation["account"].id,
                        "journal_id": third_payment_journal.id,
                        "date": move_date,
                        "employee_id": self.employee_id.id,
                        "balance": 0.0,
                    },
                )
                aggregated_line["balance"] += debit - credit

        if not aggregated_lines:
            return False

        move_lines = []
        total_debit = 0.0
        total_credit = 0.0
        for values in aggregated_lines.values():
            balance = values.pop("balance")
            if self.company_id.currency_id.is_zero(balance):
                continue
            values["debit"] = balance if balance > 0 else 0.0
            values["credit"] = -balance if balance < 0 else 0.0
            total_debit += values["debit"]
            total_credit += values["credit"]
            move_lines.append((0, 0, values))

        if not move_lines:
            return False

        if self.company_id.currency_id.is_zero(total_debit) and self.company_id.currency_id.is_zero(total_credit):
            return False

        if not self.company_id.currency_id.is_zero(total_credit):
            move_lines.append(
                (
                    0,
                    0,
                    {
                        "name": _("Pago a terceros - (%(employee)s)", employee=self.employee_id.name),
                        "partner_id": False,
                        "account_id": third_payment_journal.default_account_id.id,
                        "journal_id": third_payment_journal.id,
                        "date": move_date,
                        "employee_id": self.employee_id.id,
                        "debit": total_credit,
                        "credit": 0.0,
                    },
                )
            )
        if not self.company_id.currency_id.is_zero(total_debit):
            move_lines.append(
                (
                    0,
                    0,
                    {
                        "name": _("Pago a terceros - (%(employee)s)", employee=self.employee_id.name),
                        "partner_id": False,
                        "account_id": third_payment_journal.default_account_id.id,
                        "journal_id": third_payment_journal.id,
                        "date": move_date,
                        "employee_id": self.employee_id.id,
                        "debit": 0.0,
                        "credit": total_debit,
                    },
                )
            )

        return {
            "ref": _("%(reference)s - Terceros", reference=reference_label),
            "narration": _("%(reference)s - Pago a terceros - %(employee)s", reference=reference_label, employee=self.employee_id.name),
            "journal_id": third_payment_journal.id,
            "date": move_date,
            "line_ids": move_lines,
        }

    def _l10n_co_payroll_prepare_payment_move_vals(self):
        self.ensure_one()
        payment_journal = self.struct_id.journal_payment_id
        if not payment_journal:
            raise ValidationError(
                _(
                    "La estructura %(structure)s no tiene diario de pagos configurado.",
                    structure=self.struct_id.display_name,
                )
            )
        if not payment_journal.default_account_id:
            raise ValidationError(
                _(
                    "El diario de pagos %(journal)s no tiene cuenta por defecto configurada.",
                    journal=payment_journal.display_name,
                )
            )

        net_line = self._l10n_co_payroll_get_payment_net_line()
        if not net_line:
            raise ValidationError(
                _(
                    "La nomina de %(employee)s no tiene linea NET para generar el asiento de pago.",
                    employee=self.employee_id.name,
                )
            )

        amount = self._l10n_co_payroll_get_payment_net_amount(net_line)
        if self.company_id.currency_id.is_zero(amount):
            return False

        counterpart_account = self._l10n_co_payroll_get_payment_counterpart_account(net_line)
        if not counterpart_account:
            raise ValidationError(
                _(
                    "La linea NET de %(employee)s no tiene cuenta contable para generar el asiento de pago.",
                    employee=self.employee_id.name,
                )
            )

        partner = self._l10n_co_payroll_get_payment_partner()
        move_date = self._l10n_co_payroll_get_payment_move_date()
        benefit_move_lines = []
        benefit_total = 0.0
        if payment_journal.journal_payroll:
            benefit_move_lines, benefit_total = self._l10n_co_payroll_get_payment_benefit_move_lines(
                payment_journal, move_date, partner
            )

        counterpart_amount = amount - benefit_total
        counterpart_debit = counterpart_amount if counterpart_amount > 0 else 0.0
        counterpart_credit = -counterpart_amount if counterpart_amount < 0 else 0.0
        liquidity_debit = -amount if amount < 0 else 0.0
        liquidity_credit = amount if amount > 0 else 0.0
        reference_label = self._l10n_co_payroll_get_reference_label()
        move_lines = []

        if not self.company_id.currency_id.is_zero(counterpart_amount):
            move_lines.append(
                (
                    0,
                    0,
                    {
                        "name": _("%(name)s - (%(employee)s)", name=net_line.name or "NET", employee=self.employee_id.name),
                        "partner_id": partner.id if partner else False,
                        "account_id": counterpart_account.id,
                        "journal_id": payment_journal.id,
                        "date": move_date,
                        "employee_id": self.employee_id.id,
                        "debit": counterpart_debit,
                        "credit": counterpart_credit,
                    },
                )
            )

        move_lines.extend(benefit_move_lines)
        move_lines.append(
            (
                0,
                0,
                {
                    "name": _("%(journal)s - Total a pagar - (%(employee)s)", journal=payment_journal.name, employee=self.employee_id.name),
                    "partner_id": partner.id if partner else False,
                    "account_id": payment_journal.default_account_id.id,
                    "journal_id": payment_journal.id,
                    "date": move_date,
                    "employee_id": self.employee_id.id,
                    "debit": liquidity_debit,
                    "credit": liquidity_credit,
                },
            )
        )

        return {
            "ref": _("%(reference)s - Pago", reference=reference_label),
            "narration": _("%(reference)s - %(employee)s", reference=reference_label, employee=self.employee_id.name),
            "journal_id": payment_journal.id,
            "date": move_date,
            "line_ids": move_lines,
        }

    def _l10n_co_payroll_create_payment_moves(self):
        for payslip in self:
            if payslip.move_id_pago or payslip.state != "validated":
                continue
            move_vals = payslip._l10n_co_payroll_prepare_payment_move_vals()
            if not move_vals:
                continue
            move = self.env["account.move"].create(move_vals)
            payslip.write({"move_id_pago": move.id, "date": move.date})
        return True

    def _l10n_co_payroll_create_third_payment_moves(self):
        for payslip in self:
            if payslip.third_move_id or payslip.state != "validated":
                continue
            move_vals = payslip._l10n_co_payroll_prepare_third_payment_move_vals()
            if not move_vals:
                continue
            move = self.env["account.move"].create(move_vals)
            payslip.write({"third_move_id": move.id})
        return True

    def _l10n_co_payroll_sync_related_moves(self, raise_on_error=False):
        for payslip in self.filtered(lambda slip: slip.state == "validated"):
            if not payslip.move_id_pago:
                try:
                    if payslip._l10n_co_payroll_can_create_payment_move():
                        payslip._l10n_co_payroll_create_payment_moves()
                except ValidationError:
                    if raise_on_error:
                        raise

            if not payslip.third_move_id:
                try:
                    if payslip._l10n_co_payroll_can_create_third_payment_move():
                        payslip._l10n_co_payroll_create_third_payment_moves()
                except ValidationError:
                    if raise_on_error:
                        raise
        return True

    def _l10n_co_payroll_get_period_days(self):
        self.ensure_one()
        if not self.date_from or not self.date_to or self.date_to < self.date_from:
            return 0
        return (self.date_to - self.date_from).days + 1

    def _l10n_co_payroll_is_last_day_of_month(self):
        self.ensure_one()
        if not self.date_to:
            return False
        return self.date_to.day == calendar.monthrange(self.date_to.year, self.date_to.month)[1]

    def _l10n_co_payroll_should_apply_contract_entry(self, contract_entry):
        self.ensure_one()
        if self.liquidar_por != "nomina":
            return False
        type_payment = contract_entry.type_payment or ("both_fortnight" if contract_entry.biweekly else "monthly")
        if type_payment == "first_half":
            return bool(self.date_to and self.date_to.day <= 15)
        if type_payment in ("monthly", "second_half"):
            return self._l10n_co_payroll_is_last_day_of_month()
        if type_payment == "both_fortnight":
            return bool(self.date_to and (self.date_to.day <= 15 or self._l10n_co_payroll_is_last_day_of_month()))
        return False

    def _l10n_co_payroll_get_contract_entry_amount(self, contract_entry):
        self.ensure_one()
        if not contract_entry.type_id:
            return 0.0
        if self.liquidar_por == "definitiva":
            if not contract_entry.liquidated or not contract_entry.period:
                return 0.0
            remaining_periods = max(contract_entry.period - contract_entry.liquidated_periods, 0)
            return contract_entry.value * remaining_periods if remaining_periods else 0.0
        if contract_entry.period and contract_entry.liquidated_periods >= contract_entry.period:
            return 0.0
        if not self._l10n_co_payroll_should_apply_contract_entry(contract_entry):
            return 0.0

        amount = contract_entry.value
        if not contract_entry.absence_days:
            period_days = self._l10n_co_payroll_get_period_days()
            worked_days = min(self.dias_trabajados or 0.0, period_days or 0.0)
            if not period_days or worked_days <= 0:
                return 0.0
            amount = amount * worked_days / period_days
        return round(amount, 2)

    def _l10n_co_payroll_get_contract_input_payloads(self):
        self.ensure_one()
        payload_by_input_type = {}
        for contract_entry in self.contract_id.new_entries_ids:
            amount = self._l10n_co_payroll_get_contract_entry_amount(contract_entry)
            if amount <= 0:
                continue
            payload = payload_by_input_type.setdefault(
                contract_entry.type_id.id,
                {
                    "input_type_id": contract_entry.type_id.id,
                    "name": contract_entry.type_id.name,
                    "amount": 0.0,
                    "descriptions": [],
                    "entry_ids": [],
                },
            )
            payload["amount"] += amount
            if contract_entry.description:
                payload["descriptions"].append(contract_entry.description)
            payload["entry_ids"].append(str(contract_entry.id))
        return [
            {
                "input_type_id": payload["input_type_id"],
                "name": payload["name"],
                "amount": round(payload["amount"], 2),
                "descripcion": " - ".join(payload["descriptions"]),
                "new_entry_ids": ",".join(payload["entry_ids"]) + ("," if payload["entry_ids"] else ""),
            }
            for payload in payload_by_input_type.values()
            if payload["amount"] > 0
        ]

    def create_other_entries_from_contract(self):
        input_model = self.env["hr.payslip.input"]
        for payslip in self:
            if payslip.state != "draft":
                continue
            payslip.input_line_ids.filtered(lambda line: line.from_contract).unlink()
            if not payslip.employee_id or not payslip.contract_id or payslip.liquidar_por not in ("nomina", "definitiva"):
                continue
            for payload in payslip._l10n_co_payroll_get_contract_input_payloads():
                input_model.create(
                    {
                        "payslip_id": payslip.id,
                        "input_type_id": payload["input_type_id"],
                        "name": payload["name"],
                        "amount": payload["amount"],
                        "descripcion": payload["descripcion"],
                        "totaliza": False,
                        "from_contract": True,
                        "new_entry_ids": payload["new_entry_ids"],
                    }
                )
        return False

    def _l10n_co_payroll_update_contract_entry_periods(self, reverse=False):
        new_entry_model = self.env["new.entry"]
        for payslip in self:
            contract_lines = payslip.input_line_ids.filtered(lambda line: line.from_contract and line.new_entry_ids)
            for input_line in contract_lines:
                entry_ids = [int(entry_id) for entry_id in (input_line.new_entry_ids or "").split(",") if entry_id.isdigit()]
                contract_entries = new_entry_model.browse(entry_ids).exists()
                for contract_entry in contract_entries:
                    if payslip.liquidar_por == "definitiva":
                        if reverse:
                            if contract_entry.definitive_periods:
                                contract_entry.write(
                                    {
                                        "liquidated_periods": max(contract_entry.period - contract_entry.definitive_periods, 0),
                                        "definitive_periods": 0,
                                    }
                                )
                        else:
                            remaining_periods = max(contract_entry.period - contract_entry.liquidated_periods, 0)
                            if remaining_periods:
                                contract_entry.write(
                                    {
                                        "definitive_periods": remaining_periods,
                                        "liquidated_periods": contract_entry.period,
                                    }
                                )
                        continue
                    if reverse:
                        if contract_entry.liquidated_periods > 0:
                            contract_entry.write({"liquidated_periods": contract_entry.liquidated_periods - 1})
                    else:
                        if contract_entry.period == 0 or contract_entry.liquidated_periods < contract_entry.period:
                            contract_entry.write({"liquidated_periods": contract_entry.liquidated_periods + 1})

    def validate_info_electronic_payslip(self):
        for payslip in self:
            home_partner = payslip.employee_id._l10n_co_payroll_get_home_partner()
            if not home_partner:
                raise ValidationError("El empleado no tiene un contacto privado para nomina electronica.")
            if not payslip.company_id.ne_habilitada_compania:
                raise ValidationError("La compania no tiene habilitada la nomina electronica.")
            if not home_partner._l10n_co_payroll_get_identification_number():
                raise ValidationError("El contacto del empleado no tiene identificacion configurada.")

    @api.model
    def cron_enviar_correos(self):
        payslips_to_send = self.search(
            [
                ("state", "in", ("validated", "paid")),
                ("correo_enviado", "!=", True),
            ],
            limit=20,
        )
        payslips_to_send = payslips_to_send.filtered(lambda payslip: payslip.move_id and payslip.move_id.state == "posted")
        if not payslips_to_send:
            return True

        report_ref = self.env.ref("hr_payroll.action_report_payslip", raise_if_not_found=False)
        if not report_ref:
            return True

        attachment_model = self.env["ir.attachment"]
        for payslip in payslips_to_send:
            template = payslip.template_id or payslip._l10n_co_payroll_get_default_mail_template()
            if not template:
                continue
            pdf_content = report_ref.sudo()._render_qweb_pdf(report_ref, payslip.id)[0]
            attachment = attachment_model.create(
                {
                    "name": "%s.pdf" % (payslip.name or payslip.employee_id.name),
                    "type": "binary",
                    "datas": base64.b64encode(pdf_content),
                    "store_fname": "%s.pdf" % (payslip.name or payslip.employee_id.name),
                    "mimetype": "application/pdf",
                    "res_model": "hr.payslip",
                    "res_id": payslip.id,
                }
            )
            template.sudo().attachment_ids = [(6, 0, [attachment.id])]
            template.sudo().send_mail(payslip.id, force_send=True)
            template.sudo().attachment_ids = [(3, attachment.id)]
            payslip.correo_enviado = True
        return True

    def action_send_mail_payslip(self):
        report_ref = self.env.ref("hr_payroll.action_report_payslip", raise_if_not_found=False)
        if not report_ref:
            raise ValidationError(_("No se encontro el reporte de desprendible de nomina."))

        attachment_model = self.env["ir.attachment"]
        for payslip in self:
            template = payslip.template_id or payslip._l10n_co_payroll_get_default_mail_template()
            if not template:
                raise ValidationError(_("No se encontro una plantilla de correo para enviar el desprendible."))
            pdf_content = report_ref.sudo()._render_qweb_pdf(report_ref, payslip.id)[0]
            attachment = attachment_model.create(
                {
                    "name": "%s.pdf" % (payslip.name or payslip.employee_id.name),
                    "type": "binary",
                    "datas": base64.b64encode(pdf_content),
                    "store_fname": "%s.pdf" % (payslip.name or payslip.employee_id.name),
                    "mimetype": "application/pdf",
                    "res_model": "hr.payslip",
                    "res_id": payslip.id,
                }
            )
            template.sudo().attachment_ids = [(6, 0, [attachment.id])]
            template.sudo().send_mail(payslip.id, force_send=True)
            template.sudo().attachment_ids = [(3, attachment.id)]
            payslip.correo_enviado = True
        return False

    def action_register_payment(self):
        self.ensure_one()
        if not self.move_id:
            raise ValidationError(_("La nomina no tiene asiento contable principal para registrar el pago."))
        if self.move_id.state != "posted":
            raise ValidationError(_("El asiento contable principal debe estar publicado antes de registrar el pago."))
        bank_account = self.employee_id.sudo().bank_account_id
        return self.move_id.with_context(
            default_partner_id=self.employee_id.work_contact_id.id,
            default_partner_bank_id=bank_account.id if bank_account else False,
        ).action_register_payment()

    def action_refresh_colombian_data(self):
        draft_slips = self.filtered(lambda slip: slip.state == "draft")
        self.change_name()
        self._validate_date()
        if draft_slips:
            draft_slips.create_other_entries_from_contract()
            draft_slips.compute_sheet()
        return False

    def _l10n_co_payroll_validate_grouped_run_regeneration(self, slips, error_message):
        for payslip in slips.filtered(lambda slip: slip.company_id.batch_payroll_move_lines and slip.payslip_run_id):
            run_slips = payslip.payslip_run_id.slip_ids.filtered(lambda slip: slip.state != "cancel")
            if any(run_slip not in slips for run_slip in run_slips):
                raise ValidationError(error_message)
        return True

    def _l10n_co_payroll_get_moves_shared_outside_selection(self, field_name):
        shared_moves = self.env["account.move"]
        for move in self.mapped(field_name):
            related_slips = self.search([(field_name, "=", move.id), ("state", "!=", "cancel")])
            if related_slips - self:
                shared_moves |= move
        return shared_moves

    def regenerate_move_selection(self):
        return {
            "name": "Seleccion regenerar asientos",
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "select.regenerate.move.wizard",
            "target": "new",
            "view_id": self.env.ref("l10n_co_payroll.select_regenerate_move_wizard_view_form").id,
            "context": dict(self.env.context),
        }

    def action_regenerar_asiento(self):
        regenerate_move = self.env.context.get("regenerate_move") == "regenerate"
        regenerate_move_pago = self.env.context.get("regenerate_move_pago") == "regenerate"
        regenerate_third_move = self.env.context.get("regenerate_third_move") == "regenerate"
        if not regenerate_move and not regenerate_move_pago and not regenerate_third_move:
            return True

        if self.filtered(lambda slip: slip.state == "paid"):
            raise ValidationError("No se puede regenerar el asiento contable, de pago o de terceros de una nomina pagada.")

        if regenerate_move:
            grouped_run_slips = self.filtered(
                lambda slip: slip.company_id.batch_payroll_move_lines and slip.payslip_run_id and slip.move_id
            )
            self._l10n_co_payroll_validate_grouped_run_regeneration(
                grouped_run_slips,
                "Esta nomina pertenece a un lote con asientos agrupados. Regenera el asiento desde el lote completo.",
            )

            moves_to_remove = self.mapped("move_id").filtered(lambda move: move.state in ("draft", "cancel"))
            posted_moves = self.mapped("move_id").filtered(lambda move: move.state == "posted")
            if posted_moves:
                raise ValidationError("No se puede regenerar un asiento contable ya publicado.")

            affected_runs = self.mapped("payslip_run_id").filtered(
                lambda run: run.move_id and run.move_id in moves_to_remove
            )
            if moves_to_remove:
                moves_to_remove.with_context(force_delete=True).unlink()
            if self:
                self.write({"move_id": False})
            if affected_runs:
                affected_runs.write({"move_id": False})

            slips_to_recreate = self.filtered(lambda slip: slip.state == "validated" and slip.struct_id and slip.journal_id)
            if slips_to_recreate:
                slips_to_recreate._action_create_account_move()

        if regenerate_move_pago:
            payment_slips = self.filtered(lambda slip: slip.state == "validated" and slip.struct_id)
            grouped_payment_slips = payment_slips.filtered(
                lambda slip: slip.company_id.batch_payroll_move_lines and slip.payslip_run_id
            )
            self._l10n_co_payroll_validate_grouped_run_regeneration(
                grouped_payment_slips,
                "Esta nomina pertenece a un lote con asientos agrupados. Regenera el pago desde el lote completo.",
            )

            shared_payment_moves = self._l10n_co_payroll_get_moves_shared_outside_selection("move_id_pago")
            if shared_payment_moves:
                raise ValidationError(
                    "Hay asientos de pago compartidos entre varias nominas. Regenera el pago desde el lote completo o limpia primero esos asientos."
                )

            payment_moves_to_remove = self.mapped("move_id_pago").filtered(lambda move: move.state in ("draft", "cancel"))
            posted_payment_moves = self.mapped("move_id_pago").filtered(lambda move: move.state == "posted")
            if posted_payment_moves:
                raise ValidationError("No se puede regenerar un asiento de pago ya publicado.")
            slips_with_payment_move = self.filtered("move_id_pago")
            if payment_moves_to_remove:
                payment_moves_to_remove.with_context(force_delete=True).unlink()
            if slips_with_payment_move:
                slips_with_payment_move.write({"move_id_pago": False})

            if grouped_payment_slips:
                # Reuse the legacy accounting path so grouped batches keep one shared payment move.
                super(
                    HrPayslip,
                    grouped_payment_slips.with_context(
                        regenerate_move="no_regenerate",
                        regenerate_move_pago="regenerate",
                        regenerate_third_move="no_regenerate",
                    ),
                ).action_payslip_done()

            individual_payment_slips = payment_slips - grouped_payment_slips
            if individual_payment_slips:
                individual_payment_slips._l10n_co_payroll_create_payment_moves()

        if regenerate_third_move:
            shared_third_moves = self._l10n_co_payroll_get_moves_shared_outside_selection("third_move_id")
            if shared_third_moves:
                raise ValidationError(
                    "Hay asientos de terceros compartidos entre varias nominas. Regenera los terceros desde el lote completo o limpia primero esos asientos."
                )

            third_moves_to_remove = self.mapped("third_move_id").filtered(lambda move: move.state in ("draft", "cancel"))
            posted_third_moves = self.mapped("third_move_id").filtered(lambda move: move.state == "posted")
            if posted_third_moves:
                raise ValidationError("No se puede regenerar un asiento de terceros ya publicado.")
            slips_with_third_move = self.filtered("third_move_id")
            if third_moves_to_remove:
                third_moves_to_remove.with_context(force_delete=True).unlink()
            if slips_with_third_move:
                slips_with_third_move.write({"third_move_id": False})

            third_payment_slips = self.filtered(lambda slip: slip.state == "validated" and slip.struct_id)
            if third_payment_slips:
                third_payment_slips._l10n_co_payroll_create_third_payment_moves()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("liquidar_por", "nomina")
        payslips = super().create(vals_list)
        payslips.filtered(lambda slip: slip.state == "draft").create_other_entries_from_contract()
        return payslips

    def write(self, vals):
        res = super().write(vals)
        tracked_fields = {
            "employee_id",
            "version_id",
            "date_from",
            "date_to",
            "liquidar_por",
            "dias_vacaciones_compensadas",
            "template_id",
        }
        if tracked_fields.intersection(vals):
            draft_slips = self.filtered(lambda slip: slip.state == "draft")
            if draft_slips:
                draft_slips.change_name()
                draft_slips._validate_date()
                draft_slips.create_other_entries_from_contract()
        return res

    def _l10n_co_payroll_prepare_sheet_computation_fields(self):
        self.mapped("contract_id")
        self.mapped("wage")
        fields_to_prepare = (
            "previous_payslips_done",
            "first_day_month",
            "last_day_month",
            "dia_inicio_mes_anterior",
            "dia_fin_mes_anterior",
            "first_day_month_date_to",
            "date_from_prima",
            "date_from_cesantias",
            "dias_cesantias",
            "dias_intereses_cesantias",
            "promedio_variable_sin_extras_ni_rdominicalf_360",
            "promedio_wage_360",
            "promedio_sal_aux_tras_360",
            "promedio_sal_aux_tras_180",
            "promedio_sal_aux_tras_90",
            "smlv",
            "aux_trans",
            "valor_uvt",
            "base_fondo_solidaridad_hecho",
            "subsistence_fund_paid",
            "solidarity_fund_paid",
            "ibc_seguridad_social_mes_anterior",
        )
        for field_name in fields_to_prepare:
            self.mapped(field_name)

        stored_day_fields = (
            "dias_a_pagar",
            "dias_prima",
            "dias_trabajados",
            "dias_vacaciones",
            "days_month_date_from",
        )
        payslip_model = self.env["hr.payslip"]
        for field_name in stored_day_fields:
            payslip_model._recompute_field(payslip_model._fields[field_name])

        for field_name in stored_day_fields:
            self.mapped(field_name)
        return True

    def _l10n_co_payroll_invalidate_warning_message(self):
        self.invalidate_recordset(["warning_message"])
        return True

    def compute_sheet(self):
        draft_slips = self.filtered(lambda slip: slip.state == "draft")
        if draft_slips:
            draft_slips._l10n_co_payroll_validate_trace_variable_configuration()
            draft_slips.create_other_entries_from_contract()
            draft_slips._l10n_co_payroll_prepare_sheet_computation_fields()
        res = super().compute_sheet()
        self._l10n_co_payroll_invalidate_warning_message()
        return res

    def action_validate(self):
        draft_slips = self.filtered(lambda slip: slip.state == "draft")
        if draft_slips:
            draft_slips._l10n_co_payroll_validate_special_liquidation()
            # Avoid recomputing payslip lines that were already generated manually,
            # because the legacy compute flow appends lines instead of replacing them.
            draft_slips.filtered(lambda slip: not slip.line_ids).compute_sheet()
        res = super().action_validate()
        self._l10n_co_payroll_sync_related_moves()
        self._l10n_co_payroll_invalidate_warning_message()
        return res

    def action_payslip_done(self):
        draft_slips = self.filtered(lambda slip: slip.state == "draft")
        self.filtered(lambda slip: slip.state != "cancel")._l10n_co_payroll_validate_special_liquidation()
        res = super().action_payslip_done()
        self._l10n_co_payroll_sync_related_moves()
        draft_slips._l10n_co_payroll_update_contract_entry_periods()
        self._l10n_co_payroll_invalidate_warning_message()
        return res

    def action_payslip_cancel(self):
        slips_to_reverse = self.filtered(lambda slip: slip.state in ("validated", "paid"))
        res = super().action_payslip_cancel()
        slips_to_reverse._l10n_co_payroll_update_contract_entry_periods(reverse=True)
        return res
