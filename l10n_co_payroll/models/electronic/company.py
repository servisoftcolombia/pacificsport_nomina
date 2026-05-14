# -*- coding:utf-8 -*-
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class Company(models.Model):
    _inherit = "res.company"

    nomina_electronica_id = fields.Char(string="ID para nomina electronica")
    ne_certificado = fields.Binary(string="Certificado NE")
    ne_certificado_password = fields.Char(string="Contrasena del certificado NE (BD)")
    view_ne_certificado_password = fields.Char(string="Contrasena del certificado NE")
    ne_software_id = fields.Char(string="ID de software NE (BD)")
    ne_software_pin = fields.Char(string="PIN de software NE (BD)")
    view_ne_software_pin = fields.Char(string="PIN de software NE")
    ne_url_politica_firma = fields.Char(
        string="URL Politica de firma NE",
        default="https://dian.gov.co/normatividad/DocumentosVisores/visor.html?file=DIAN-Politicadefirma-V2.pdf",
    )
    ne_archivo_politica_firma = fields.Binary(string="Archivo de politica de firma NE")
    ne_descripcion_politica_firma = fields.Char(
        string="Descripcion politica de firma NE",
        default="Politica de firma para Nomina Electronica de la DIAN",
    )
    ne_tipo_ambiente = fields.Selection(
        selection=[("1", "Produccion"), ("2", "Pruebas DIAN")],
        string="Ambiente de destino NE",
        default="2",
    )
    ne_test_set_id = fields.Char(string="ID para set de pruebas NE")
    ne_nomina_email = fields.Char(string="Correo del responsable de nomina NE")
    ne_habilitada_compania = fields.Boolean(string="Habilitar Nomina Electronica")
    secuencia_nomina_individual_electronica = fields.Many2one("ir.sequence", string="Secuencia Nomina Individual Electronica (NIE)")
    secuencia_nomina_individual_ajuste = fields.Many2one("ir.sequence", string="Secuencia Nomina Individual de Ajuste (NIA)")
    fecha_inicio_reporte_nominas_electronicas = fields.Date(string="Fecha inicio reporte nominas electronicas")

    @staticmethod
    def _l10n_co_payroll_is_valid_url(url):
        parsed = urlparse(url or "")
        return bool(parsed.scheme and parsed.netloc)

    def _l10n_co_payroll_prepare_ne_values(self, values):
        values = dict(values)
        company = self[:1]
        ne_enabled = values.get("ne_habilitada_compania", company.ne_habilitada_compania if company else False)
        if not ne_enabled:
            return values

        url = values.get("ne_url_politica_firma", company.ne_url_politica_firma if company else False)
        if url and not self._l10n_co_payroll_is_valid_url(url):
            raise ValidationError(_("La URL para politica de firma de Nomina Electronica es invalida: %s") % url)

        certificate_password = values.get("view_ne_certificado_password")
        if certificate_password is not None:
            values["ne_certificado_password"] = certificate_password
            values["view_ne_certificado_password"] = False
        elif not values.get("ne_certificado_password", company.ne_certificado_password if company else False):
            raise ValidationError(_("Debe diligenciar la contrasena del certificado para Nomina Electronica."))

        software_pin = values.get("view_ne_software_pin")
        if software_pin is not None:
            values["ne_software_pin"] = software_pin
            values["view_ne_software_pin"] = False
        elif not values.get("ne_software_pin", company.ne_software_pin if company else False):
            raise ValidationError(_("Debe diligenciar el PIN del software para Nomina Electronica."))

        return values

    @api.model
    def create(self, values):
        values = self._l10n_co_payroll_prepare_ne_values(values)
        return super().create(values)

    def write(self, values):
        for company in self:
            values = company._l10n_co_payroll_prepare_ne_values(values)
        return super().write(values)
