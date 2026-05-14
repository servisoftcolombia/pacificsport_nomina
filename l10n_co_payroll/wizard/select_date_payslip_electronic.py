from odoo import api, fields, models
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class SelectDatePayslipElectronicWizard(models.TransientModel):
    _name = "select.date.payslip.electronic.wizard"
    _description = "Select Date Payslip Electronic"

    # Si es enero, que seleccione diciembre del año anterior
    month = fields.Selection(
        [('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'), ('5', 'Mayo'), ('6', 'Junio'),
         ('7', 'Julio'), ('8', 'Agosto'), ('9', 'Septiembre'), ('10', 'Octubre'), ('11', 'Noviembre'),
         ('12', 'Diciembre')],
        string='Mes',
        default=lambda self: str(12 if datetime.now().month == 1 else datetime.now().month - 1),
        required=True,
    )

    # Ajusta el año si el mes predeterminado es diciembre del año anterior
    year = fields.Selection(
        selection='years_selection',
        string="Año",
        default=lambda self: str(datetime.now().year - 1 if datetime.now().month == 1 else datetime.now().year),
        required=True
    )

    company_id = fields.Many2many('res.company', string='Compañia', default=lambda self: self.env.user.company_ids)

    def years_selection(self):
        """Genera una lista de años desde el más antiguo payslip disponible"""
        payslip = self.env['hr.payslip'].search(
            [('liquidar_por', 'in', ('nomina', 'vacaciones', 'definitiva')),
             ('state', 'in', ['validated', 'paid']), ('payslip_electronic_id', '=', False)],
            order='date_from', limit=1)
        current_year = str(datetime.now().year)
        year_list = set()

        # Añadir los años desde el más reciente al más antiguo
        if payslip:
            for y in range(int(current_year), int(payslip.date_from.year) - 1, -1):
                year_list.add((str(y), str(y)))
        else:
            year_list.add((current_year, current_year))

        # Asegurar que el año anterior esté presente
        year_list.add((str(int(current_year) - 1), str(int(current_year) - 1)))

        # Convertir a lista ordenada para mantener la estructura original
        return sorted(year_list, reverse=True)

    def create_payslip_electronic_date(self):
        try:
            # Validar si se debe restar un año
            year = int(self.year)
            month = int(self.month)

            # Calcula los meses con ajuste de año
            months = (datetime.now().year - year) * 12 + datetime.now().month - month

            # Crear el objeto de nómina electrónica
            report = self.env['hr.payslip.electronic']
            report.cron_creacion_xml(months, self.company_id)
        except Exception as e:
            _logger.error(f"Error creando nómina electrónica: {e}")
            raise e
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
