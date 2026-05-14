# -*- encoding: utf-8 -*-

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SalaryRuleCategory(models.Model):
    _inherit = 'hr.salary.rule.category'

    company_id = fields.Many2one(
        'res.company', 'Company',
        default=lambda self: self.env.company.id,
        required=True
    )


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    company_id = fields.Many2one(
        'res.company', 'Company',
        default=lambda self: self.env.company.id,
        required=True
    )

    account_rule = fields.One2many('salary.rule.account', 'regla_salarial')
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
        string='Tipo de tercero')

    partner_id = fields.Many2one('res.partner', 'Tercero')
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Cuenta analitica',
        compute='_compute_l10n_co_payroll_analytic_account_id',
    )
    regulation = fields.Text(string='Norma', help='Normatividad que rige la regla salarial.')
    functional_information = fields.Text(string='Información Funcional', help='Información acerca del funcionamiento de la regla en odoo.')

    @api.depends('analytic_distribution')
    def _compute_l10n_co_payroll_analytic_account_id(self):
        for rule in self:
            analytic_account_id = False
            distribution = rule.analytic_distribution or {}
            if isinstance(distribution, dict):
                numeric_keys = [(int(key), value) for key, value in distribution.items() if str(key).isdigit()]
                if numeric_keys:
                    numeric_keys.sort(key=lambda item: (-item[1], item[0]))
                    analytic_account_id = numeric_keys[0][0]
            rule.analytic_account_id = analytic_account_id

    @api.model
    def _compute_rule(self, localdict):
        data = super(HrSalaryRule, self)._compute_rule(localdict=localdict)
        precision = self.env['decimal.precision'].precision_get('Payroll')
        return round(data[0], precision), data[1], data[2]

    def logger(self, text=False, values=False, type="info"):
        '''
        Generate logger with text received, join values received
        :param str text: text to show in log, the format of text is "text to show {} in bracket the function set values in order".
        :param list values: list of values to join to text.
        :param string type : type of log: info, warning, error
        '''

        if not values:
            if not text:
                raise UserError("Insert values or text parameter.")

        if text:
            if values:
                pos = 0
                while text.find("{}") >= 0:
                    if pos < len(values):
                        text = text.replace("{}", str(values[pos]), 1)
                        pos += 1
                    else:
                        raise UserError("Format error in text or values.")

        else:
            text = ' '.join(values)

        if type == 'info':
            _logger.info(text)
        elif type == 'warning':
            _logger.warning(text)
        elif type == 'error':
            _logger.error(text)
        else:
            raise UserError("Type error.")


class hr_payroll_structure_co(models.Model):
    _inherit = 'hr.payroll.structure'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    type = fields.Selection(string='Tipo estructura', selection=[('contract', 'Contract'), ('payroll', 'Payroll')])
    journal_payment_id = fields.Many2one('account.journal', 'Diario de pagos', readonly=False, company_dependent=True)
    journal_third_payment_id = fields.Many2one('account.journal', 'Diario de pagos a terceros', readonly=False, company_dependent=True)
    account_receivable_employee_id = fields.Many2one('account.account', 'Cuenta por cobrar empleado', readonly=False, company_dependent=True)
