# -*- encoding: utf-8 -*-


# PragmaTIC (om) 2015-07-03 actualiza para version 8
from odoo import models, fields


# Agrega campos Caja, ARL, ICBF, SENA, Salario mínimo, Salario mínimo integral, UVT  en datos del empleado.
# PragmaTIC (om) 2015-07-03 Agrega nivel de riesgo ARL, AFC, FPV, intereses de vivienda, medicina prepagada y dependientes

class ResCompany(models.Model):

    _inherit = 'res.company'
    ccf_id = fields.Many2one('res.partner', string='Caja de comp. familiar')
    arl_id = fields.Many2one('res.partner', string='ARL')
    icbf_id = fields.Many2one('res.partner', string='ICBF')
    sena_id = fields.Many2one('res.partner', string='SENA')
    dian_id = fields.Many2one('res.partner', string='DIAN')
    ley_1607 = fields.Boolean(string='Acogido ley 1607/2012')
    anticipated_vacation_limit = fields.Integer(string="Limite vacaciones anticipadas", help="Limita la cantidad máxima de vacaciones que puede tener un empleado.\nSi se configura en 0 no hay limite.")
    licenses_as_suspension = fields.Boolean(help="Las licencias no remuneradas no se tendran en cuenta en el calculo del promedio para el pago de la prima")
    vacations_in_average = fields.Boolean(help="Si está activo las vacaciones se toman en cuenta para el cálculo del variable con el valor que tienen, si está inactivo el tiempo de vacaciones se toma con el valor del sueldo de ese momento por los días de vacaciones.",
                                          default=True)
    vacations_in_average_of_vacations = fields.Boolean(help="Si se habilita se calcula el promedio para base de vacaciones con los valores de las vacaciones tomadas, Si no está habilitado los días de vacaciones los toma con el valor de salario diario.",
                                                       default=True)
    vacations_salary_base_as_average = fields.Boolean(help="Si el check está activo toma el último salario más el promedio de lo variable como base para el pago de las vacaciones, si el check no está activado toma el promedio del salario devengado en los últimos 12 meses, más el variable en esos 12 meses.",
                                                      default=True)
    average_in_fixed_salary = fields.Boolean(help="Si el check está activo, la base para el cálculo de la prima se realiza con el promedio de los últimos 6 meses. Si el check está desactivado la base para el cálculo de la prima se realiza con el salario actual y el auxilio de transporte si aplica.",
                                             default=True)
    all_aux_tra_in_average_fixed_salary = fields.Boolean(help=" Si el check está activo, en el cálculo del promedio para la prima para empleados de salario fijo, se toma en cuenta el valor del auxilio de transporte en su totalidad así haya tenido un valor inferior debido a vacaciones o incapacidades.")
    all_aux_tra_in_average_variable_salary = fields.Boolean(help=" Si el check está activo, en el cálculo del promedio para la prima para empleados de salario variable, se toma en cuenta el valor del auxilio de transporte en su totalidad así haya tenido un valor inferior debido a vacaciones o incapacidades.")
    disability_one_hundred_average_fixed_salary = fields.Boolean(help="Si el check está activo, los días de incapacidad los toma pagados al 100% para el cálculo del promedio de la prima, de lo contrario toma en cuenta solo el porcentaje pagado para salario fijo.",
                                                                 default=True)
    disability_one_hundred_average_variable_salary = fields.Boolean(help="Si el check está activo, los días de incapacidad los toma pagados al 100% para el cálculo del promedio de la prima, de lo contrario toma en cuenta solo el porcentaje pagado para salario variable",
                                                                    default=True)
    all_aux_tra_in_severance_fixed_salary = fields.Boolean(help="Para el cálculo de las cesantias en empleados con salario fijo: \nActivo: Se toma el valor del auxilio de transporte en su totalidad. \nInactivo: Se toma el valor del auxilio de transporte solamente lo pagado.")

    all_aux_tra_in_severance_variable_salary = fields.Boolean(help="Para el cálculo de las cesantias en empleados con salario variable: \nActivo: Se toma el valor del auxilio de transporte en su totalidad. \nInactivo: Se toma el valor del auxilio de transporte solamente lo pagado.")

    last_salary_in_severance_fixed_salary = fields.Boolean(help="Para el cálculo de las cesantias en empleados con salario fijo se tomara siempre el último salario.")
    
    limit_40_percent_parafiscal_base = fields.Boolean(help="Calcular límite del 40% a los pagos no constitutivos de salario para la base de parafiscales. \nActivo: Se tiene en cuenta el 40% a los pagos no constitutivos de salario para la base de parafiscales. \nInactivo: No se realiza el calculo del 40% a los pagos no constitutivos de salario para la base de parafiscales.")

    aplicada = fields.Boolean(string='Aplicación de Plantilla')
    pcts_incapacidades = fields.Many2one(
        "funcion.trozo",
        default=lambda self: self.env.ref("l10n_co_payroll.ft_pcts_incapacidades", raise_if_not_found=False),
    )

    _check_anticipated_vacation_limit = models.Constraint(
        'CHECK(anticipated_vacation_limit >= 0)',
        'El limite vacaciones anticipadas debe ser un valor mayor o igual a cero.',
    )
