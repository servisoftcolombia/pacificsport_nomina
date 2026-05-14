import logging
from collections import defaultdict, Counter
from odoo import fields, models

_logger = logging.getLogger(__name__)


class DefaultDictPayroll(defaultdict):
    def get(self, key, default=None):
        if key not in self and default is not None:
            self[key] = default
        return self[key]


class hr_payslip_line(models.Model):
    _inherit = 'hr.payslip.line'

    origin_partner = fields.Selection(
        selection=[('employee', 'Empleado'),
                   ('eps', 'EPS'),
                   ('fp', 'Fondo de Pensiones'),
                   ('fc', 'Fondo de cesantías'),
                   ('ccf', 'Caja de compens. Famil.'),
                   ('arl', 'ARL'),
                   ('icbf', 'ICBF'),
                   ('sena', 'SENA'),
                   ('dian', 'DIAN'),
                   ('rule', 'Regla salarial')],
        string='Tipo de tercero', required=False)

    def write(self, vals):
        writed = super(hr_payslip_line, self).write(vals)
        if 'amount' in vals and self.code not in ('TOTAL_DEDUCCION', 'BRU', 'NET'):
            self.recalcular_subtotales()
        return writed

    def recalcular_subtotales(self):
        slip_id = self.slip_id
        _logger.info('slip_id: {}'.format(slip_id))
        result = {}
        rules_dict = {}
        worked_days_dict = {line.code: line for line in slip_id.worked_days_line_ids if line.code}
        inputs_dict = {line.code: line for line in slip_id.input_line_ids if line.code}
        employee = slip_id.employee_id
        contract = slip_id.contract_id
        localdict_lines = {}
        lines = self.env['hr.payslip.line'].search([('id', 'in', slip_id.line_ids.ids)])
        dict_categories = {}
        for line in lines:
            localdict_lines.update({
                '{}'.format(line.code): line.amount})
            cat = self.env['hr.salary.rule.category'].search([('id', '=', line.category_id.id)])
            if cat.code in dict_categories:
                val = dict_categories[cat.code] + line.amount
            else:
                val = line.amount
            dict_categories.update({cat.code: val})
            if cat.parent_id:
                if cat.parent_id.code in dict_categories:
                    val = dict_categories[cat.parent_id.code] + line.amount
                else:
                    val = line.amount

                dict_categories.update({cat.parent_id.code: val})
        localdict = {
            **slip_id._get_base_local_dict(),
            **{
                'categories': DefaultDictPayroll(lambda: 0),
                'rules': DefaultDictPayroll(lambda: dict(total=0, amount=0, quantity=0)),
                'payslip': self,
                'worked_days': {line.code: line for line in self.worked_days_line_ids if line.code},
                'inputs': {line.code: line for line in self.input_line_ids if line.code},
                'employee': self.employee_id,
                'contract': self.contract_id,
                'result_rules': DefaultDictPayroll(lambda: dict(total=0, amount=0, quantity=0, rate=0)),
                'result': True,
                'result_qty': 1.0,
                'result_rate': 100
            }
        }
        localdict.update(localdict_lines)

        total_deducciones = self.env['hr.salary.rule'].search([('code', '=', 'TOTAL_DEDUCCION')])
        localdict['categories'].dict[total_deducciones.code] = localdict['categories'].dict.get(total_deducciones.code,
                                                                                                0)
        amount, qty, rate = total_deducciones._compute_rule(localdict)
        total_deducciones_line = self.env['hr.payslip.line'].search(
            [('code', '=', 'TOTAL_DEDUCCION'), ('id', 'in', slip_id.line_ids.ids)])
        if total_deducciones_line:
            total_deducciones_line.write({'amount': amount, 'quantity': qty, 'rate': rate})
        _logger.info('slip_id : {} TOTAL_DEDUCCION: amount {}, qty: {}, rate {}'.format(slip_id, amount, qty, rate))

        subtotal_ingresos = self.env['hr.salary.rule'].search([('code', '=', 'BRU')])
        localdict['categories'].dict[subtotal_ingresos.code] = localdict['categories'].dict.get(subtotal_ingresos.code,
                                                                                                0)
        amount, qty, rate = subtotal_ingresos._compute_rule(localdict)
        _logger.info('slip_id: {} BRU: amount {}, qty: {}, rate {}'.format(slip_id, amount, qty, rate))
        subtotal_ingresos_line = self.env['hr.payslip.line'].search(
            [('code', '=', 'BRU'), ('id', 'in', slip_id.line_ids.ids)])
        if subtotal_ingresos_line:
            subtotal_ingresos_line.write({'amount': amount, 'quantity': qty, 'rate': rate})

        total_a_pagar = self.env['hr.salary.rule'].search([('code', '=', 'NET')])
        localdict['categories'].dict[total_a_pagar.code] = localdict['categories'].dict.get(total_a_pagar.code, 0)
        amount, qty, rate = total_a_pagar._compute_rule(localdict)
        _logger.info('slip_id: {} NET: amount {}, qty: {}, rate {}'.format(slip_id, amount, qty, rate))
        total_a_pagar_line = self.env['hr.payslip.line'].search(
            [('code', '=', 'NET'), ('id', 'in', slip_id.line_ids.ids)])
        if total_a_pagar_line:
            total_a_pagar_line.write({'amount': amount, 'quantity': qty, 'rate': rate})