import pytz
from collections import defaultdict
from datetime import datetime, time, date

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _


class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'

    def _get_employees(self):
        return self.env['hr.employee']

    def _check_undefined_slots(self, work_entries, payslip_run):
        """
        Check if a time slot in the contract's calendar is not covered by a work entry
        """
        work_entries_by_contract = defaultdict(lambda: self.env['hr.work.entry'])
        for work_entry in work_entries:
            work_entries_by_contract[work_entry.contract_id] |= work_entry

        for contract, work_entries in work_entries_by_contract.items():
            calendar_start = pytz.utc.localize(
                datetime.combine(max(contract.date_start, payslip_run.date_start), time.min))
            calendar_end = pytz.utc.localize(
                datetime.combine(min(contract.date_end or date.max, payslip_run.date_end), time.max))
            outside = contract.resource_calendar_id._attendance_intervals_batch(calendar_start, calendar_end)[
                False] - work_entries._to_intervals()

    def compute_sheet(self):
        self.ensure_one()
        if not self.env.context.get('active_id'):
            from_date = fields.Date.to_date(self.env.context.get('default_date_start'))
            end_date = fields.Date.to_date(self.env.context.get('default_date_end'))
            payslip_run = self.env['hr.payslip.run'].create({
                'name': from_date.strftime('%B %Y'),
                'date_start': from_date,
                'date_end': end_date,
            })
        else:
            payslip_run = self.env['hr.payslip.run'].browse(self.env.context.get('active_id'))

        contratos_previos = self.env['hr.payslip'].search([("payslip_run_id", "=", payslip_run.id)]).mapped(
            "contract_id")

        if not self.employee_ids:
            raise UserError(_("You must select employee(s) to generate payslip(s)."))

        payslips = self.env['hr.payslip']
        Payslip = self.env['hr.payslip']
        payslip_run_date_start = datetime.combine(payslip_run.date_start, datetime.min.time())
        payslip_run_date_end = datetime.combine(payslip_run.date_end, datetime.min.time())

        contracts = self.employee_ids._get_contracts(payslip_run_date_start, payslip_run_date_end,
                                                     states=['open', 'close']) - contratos_previos
        contracts._generate_work_entries(payslip_run_date_start, payslip_run_date_end)
        work_entries = self.env['hr.work.entry'].search([
            ('date_start', '<=', payslip_run_date_end),
            ('date_stop', '>=', payslip_run_date_start),
            ('employee_id', 'in', self.employee_ids.ids),
        ])
        self._check_undefined_slots(work_entries, payslip_run)

        validated = work_entries.action_validate()
        if not validated:
            raise UserError(_("Some work entries could not be validated."))

        default_values = Payslip.default_get(Payslip.fields_get())
        for contract in contracts:
            values = dict(default_values, **{
                'employee_id': contract.employee_id.id,
                # 'credit_note': payslip_run.credit_note,
                'payslip_run_id': payslip_run.id,
                'date_from': payslip_run_date_start,
                'date_to': payslip_run_date_end,
                'contract_id': contract.id,
                'struct_id': self.structure_id.id or contract.structure_type_id.default_struct_id.id,
            })
            payslip = self.env['hr.payslip'].new(values)
            payslip._onchange_employee()
            values = payslip._convert_to_write(payslip._cache)

            # @TODO
            # Codigo temporal para evitar que se eliminen las nominas reglas de las nominas previas en odoo 14 y 15
            # previous_payslips_done = values.get('previous_payslips_done')
            # if len(previous_payslips_done) > 1:
            #     previous_payslips_done = previous_payslips_done[0]
            #     values.update({'previous_payslips_done': [previous_payslips_done]})

            payslips += Payslip.create(values)
        # Se comenta por que esta haciendo calcular_entradas dos veces
        # for payslip in payslips:
        #     payslip._calcular_entradas()
        payslips.compute_sheet()
        payslip_run.state = 'verify'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip.run',
            'views': [[False, 'form']],
            'res_id': payslip_run.id,
        }
