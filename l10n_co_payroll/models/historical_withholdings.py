from datetime import date

import calendar

from odoo import api, fields, models


class HistoricalWithholdings(models.Model):
    _name = "historical.withholdings"
    _description = "Historical Withholdings"
    _rec_name = "percentage_value"

    percentage_value = fields.Float(string="Percentage value", required=True)
    period_from = fields.Date(string="Period From")
    period_to = fields.Date(string="Period To")
    contract_id = fields.Many2one("hr.version", string="Payroll Record", ondelete="set null")
    percentage_update_date = fields.Date(string="Percentage update date")

    @api.onchange('percentage_value')
    def onchange_percentage_value(self, today=False):
        reference_date = fields.Date.to_date(today) if today else fields.Date.context_today(self)
        self.percentage_update_date = reference_date
        month = reference_date.month
        year = reference_date.year

        # Si el mes actual es Julio asigna fechas desde 1 Julio hasta ultimo Diciembre
        if month == 7:
            self.period_from = self.first_day_of_month(in_year=year, in_month=7)
            self.period_to = self.last_day_of_month(in_month=12, in_year=year)

        # Si el mes actual es Enero asigna 1 de Enero hasta ultimo de Junio del siguiente año
        if month == 1:
            self.period_from = self.first_day_of_month(in_year=year, in_month=1)
            self.period_to = self.last_day_of_month(in_month=6, in_year=year)

    def first_day_of_month(self, in_month=False, in_year=False):
        """
        Obtiene el primer dia del mes en un año y mes indicado

        :in_month: mes del que se desea obtener, por defecto el actual
        :in_year: año del que se desea obtener, por defecto el actual
        :return: date con el primer dia del mes y año requerido
        """
        month = in_month or date.today().month
        year = in_year or date.today().year
        return date(year, month, 1)

    def last_day_of_month(self, in_month=False, in_year=False):
        """
        Obtiene el ultimo dia del mes en un año y mes indicado

        :in_month: mes del que se desea obtener, por defecto el actual
        :in_year: año del que se desea obtener, por defecto el actual
        :return: date con el ultimo dia del mes y año requerido
        """
        month = in_month or date.today().month
        year = in_year or date.today().year
        return date(year, month, calendar.monthrange(year, month)[1])
