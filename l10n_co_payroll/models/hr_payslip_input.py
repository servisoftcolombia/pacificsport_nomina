from odoo import fields, models
from odoo.exceptions import ValidationError


class HrPayslipInput(models.Model):
    _inherit = 'hr.payslip.input'

    totaliza = fields.Boolean(string="Totaliza", default=False)
    descripcion = fields.Char(string="Descripcion")
    from_contract = fields.Boolean(string='Proviene del contrato')
    new_entry_ids = fields.Char(string='ids de novedades', default='ids: ')

    def write(self, vals):
        writed = super(HrPayslipInput, self).write(vals)
        if 'input_type_id' in vals:
            input_types = self.env['hr.payslip.input.type'].search([('id', '=', vals['input_type_id'])])
        elif self.input_type_id:
            input_types = self.env['hr.payslip.input.type'].search([('id', '=', self.input_type_id.id)])
        if 'descripcion' in vals:
            for input_type in input_types:
                if input_type.code in ('SINDICATOS', 'VACACIONES_COMPENSADAS', 'HED', 'HEN', 'HRN', 'HEDDF', 'HENDF', 'HRDDF', 'HRNDF'):
                    try:
                        value = int(float(vals['descripcion'].strip().replace(",", ".")))
                    except Exception:
                        raise ValidationError(
                            'El campo descripcion para la entrada de {}, debe ser numérico.'.format(input_type.code))
                elif input_type.code in ('LIBRANZAS', 'OTRO_DEVENGADO_S', 'OTRO_DEVENGADO_NS'):
                    if vals['descripcion'] == '' or not vals['descripcion']:
                        raise ValidationError(
                            'El campo descripcion para la entrada de {}, se debe indicar'.format(input_type.code))
        elif self.descripcion:
            for input_type in input_types:
                if input_type.code in ('SINDICATOS', 'VACACIONES_COMPENSADAS', 'HED', 'HEN', 'HRN', 'HEDDF', 'HENDF', 'HRDDF', 'HRNDF'):
                    try:
                        value = int(float(self.descripcion.strip().replace(",", ".")))
                    except Exception:
                        raise ValidationError(
                            'El campo descripcion para la entrada de {}, debe ser numérico.'.format(input_type.code))
                elif input_type.code in ('LIBRANZAS', 'OTRO_DEVENGADO_S', 'OTRO_DEVENGADO_NS'):
                    if self.descripcion == '':
                        raise ValidationError(
                            'El campo descripcion para la entrada de {}, se debe indicar'.format(input_type.code))
        else:
            for input_type in input_types:
                if input_type.code in ('SINDICATOS', 'VACACIONES_COMPENSADAS', 'HED', 'HEN', 'HRN', 'HEDDF', 'HENDF', 'HRDDF', 'HRNDF'):
                    raise ValidationError(
                        'El campo descripcion para la entrada de {}, se debe indicar y debe ser numérico.'.format(
                            input_type.code))
                elif input_type.code in ('LIBRANZAS', 'OTRO_DEVENGADO_S', 'OTRO_DEVENGADO_NS'):
                    raise ValidationError(
                        'El campo descripcion para la entrada de {}, se debe indicar.'.format(input_type.code))

        return writed

    def create(self, vals):
        created = super(HrPayslipInput, self).create(vals)
        for input in created:
            if 'input_type_id' in vals:
                input_types = self.env['hr.payslip.input.type'].search([('id', '=', vals['input_type_id'])])
            elif input.input_type_id:
                input_types = self.env['hr.payslip.input.type'].search([('id', '=', input.input_type_id.id)])
            if 'descripcion' in vals:
                for input_type in input_types:
                    if input_type.code in (
                    'SINDICATOS', 'VACACIONES_COMPENSADAS', 'HED', 'HEN', 'HRN', 'HEDDF', 'HENDF', 'HRDDF', 'HRNDF'):
                        try:
                            value = int(float(vals['descripcion'].strip().replace(",", ".")))
                        except:
                            raise ValidationError(
                                'El campo descripcion para la entrada de {}, debe ser numérico.'.format(
                                    input_type.code))
                    elif input_type.code in ('LIBRANZAS', 'OTRO_DEVENGADO_S', 'OTRO_DEVENGADO_NS'):
                        if vals['descripcion'] == '':
                            raise ValidationError(
                                'El campo descripcion para la entrada de {}, se debe indicar'.format(input_type.code))
            elif input.descripcion:
                for input_type in input_types:
                    if input_type.code in (
                    'SINDICATOS', 'VACACIONES_COMPENSADAS', 'HED', 'HEN', 'HRN', 'HEDDF', 'HENDF', 'HRDDF', 'HRNDF'):
                        try:
                            value = int(float(input.descripcion.strip().replace(",", ".")))
                        except:
                            raise ValidationError(
                                'El campo descripcion para la entrada de {}, debe ser numérico.'.format(
                                    input_type.code))
                    elif input_type.code in ('LIBRANZAS', 'OTRO_DEVENGADO_S', 'OTRO_DEVENGADO_NS'):
                        if input.descripcion == '':
                            raise ValidationError(
                                'El campo descripcion para la entrada de {}, se debe indicar'.format(input_type.code))
            else:
                for input_type in input_types:
                    if input_type.code in (
                    'SINDICATOS', 'VACACIONES_COMPENSADAS', 'HED', 'HEN', 'HRN', 'HEDDF', 'HENDF', 'HRDDF', 'HRNDF'):
                        raise ValidationError(
                            'El campo descripcion para la entrada de {}, se debe indicar y debe ser numérico.'.format(
                                input_type.code))
                    elif input_type.code in ('LIBRANZAS', 'OTRO_DEVENGADO_S', 'OTRO_DEVENGADO_NS'):
                        raise ValidationError(
                            'El campo descripcion para la entrada de {}, se debe indicar.'.format(input_type.code))
        return created


class HrPayslipInputType(models.Model):
    _inherit = 'hr.payslip.input.type'

    appear_contract = fields.Boolean(string='Aparece en las opciones del contrato')
