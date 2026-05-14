# -*- encoding: utf-8 -*-


from odoo import fields, models


class IntervaloCalendario(models.Model):
    _name = "intervalo.calendario"
    _description = "intervalo calendario"
    _order = "date_from"

    contract_id = fields.Many2one("hr.version", string="Registro salarial", ondelete="cascade")
    date_from = fields.Date(string="Fecha desde", required=True)
    date_to = fields.Date(string="Fecha hasta", required=True)
    calendar_id = fields.Many2one("resource.calendar", string="Calendario", required=True)
