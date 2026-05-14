from odoo import api, fields, models, tools
from odoo.fields import Domain
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
from odoo.tools.translate import _
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class Holidays(models.Model):
    _inherit = "hr.leave"
    payslip_input_id = fields.Many2one('hr.payslip.input', string='Entrada de nomina')
    remaining_addition = fields.Float(help='Almacena el valor adicionado desde el ultimo cumplemes del contrato hasta la fecha de la definitiva')
    book_vacations_id = fields.Many2one("book.vacations", compute="_compute_book_vacations_id")
    value_vacations = fields.Float(string="Valor", compute="_compute_value_vacations")
    contract_id = fields.Many2one(
        'hr.contract',
        string='Contrato',
        help='Contrato al que pertenece la ausencia (Para empleados que han tenido mas de un contrato',
        domain=lambda self: [('employee_id', '=', self.employee_id.id)]
    )
    number_of_days_calendar = fields.Float(string="Dias Calendario", copy=False, help='Numero de días calendario desde la fecha de inicio hasta la fecha de finalización')
    work_entry_type_code = fields.Char(string='Código tipo de ausencia', related='holiday_status_id.work_entry_type_id.code', help='Permite identificar el código del tipo de ausencia')
    contract_manager = fields.Boolean(
        string='Administrador de contratos',
        compute="_compute_contract_manager",
        default=lambda self: self.env.user.has_group('hr_contract.group_hr_contract_manager'),
        help='Permite identificar si el usuario logeado tiene permisos de administrador de contratos.'
    )

    def _compute_book_vacations_id(self):
        for leave in self:
            # Asignar a la ausencia el libro correspondiente al empleado para el campo One2Many leaves_ids en book.vactions
            if leave.holiday_status_id.work_entry_type_id.code == 'VAC':
                book_vacation = self.env['book.vacations'].search(
                    [('contract_id', '=', leave.contract_id.id)], limit=1)
                if book_vacation:
                    leave.book_vacations_id = book_vacation
                else:
                    leave.book_vacations_id = None
            else:
                leave.book_vacations_id = None

    def _compute_value_vacations(self):
        for leave in self:
            # Si la ausencia fue generada desde nomina (vac. compensadas), debe tener un valor, de lo contrario se busca
            # Una nomina de vacaciones dentro del periodo de la ausencia
            if leave.payslip_input_id:
                leave.value_vacations = leave.payslip_input_id.amount
            elif leave.holiday_status_id.work_entry_type_id.code == 'VAC':
                payslips = self.env['hr.payslip'].search(
                    [('employee_id', '=', leave.employee_id.id),
                     ('liquidar_por', '=', 'vacaciones'),
                     ('state', '=', 'done'),
                     ('date_from', '>=', leave.date_from.date()),
                     ('date_to', '<=', leave.date_to.date())])
                if payslips:
                    for payslip in payslips:
                        for pay in payslip.line_ids:
                            if pay.code == "ING_SAL":
                                leave.value_vacations += pay.amount
                else:
                    leave.value_vacations = None
            else:
                leave.value_vacations = None

    def _compute_contract_manager(self):
        self.contract_manager = self.env.user.has_group('hr_contract.group_hr_contract_manager')

    @api.onchange('employee_id')
    def _default_contract(self):
        contract_id = self.env['hr.contract'].sudo().search([('employee_id', '=', self.employee_id.id if self.employee_id else None), ('state', '=', 'open')])
        # Validar tipos de permisos en modulo ausencias y contrato
        holidays_manager = self.env.user.has_group('hr_holidays.group_hr_holidays_manager')
        holidays_user = self.env.user.has_group('hr_holidays.group_hr_holidays_user')
        holidays_responsible = self.env.user.has_group('hr_holidays.group_hr_holidays_responsible')
        # holidays_permission = True si tiene algun tipo de permiso de ausencias
        holidays_permission = holidays_manager or holidays_user or holidays_responsible
        contract_manager = self.env.user.has_group('hr_contract.group_hr_contract_manager')

        if self.employee_id and not contract_id:
            if self.env.uid != self.employee_id.user_id.id:
                raise UserError('El empleado no tienen un contrato activo.')
            elif self.env.uid == self.employee_id.user_id.id and not holidays_permission and not contract_manager:
                raise UserError('El empleado no tienen un contrato activo.')

        self.contract_id = contract_id

    @api.onchange('date_from', 'date_to')
    def _onchange_leave_dates_calendar(self):
        '''Calculate days calendar from leave'''
        if self.date_from and self.date_to:
            date_from = self.date_from.replace(hour=0, minute=0, second=0)
            # The date date_to go to 23:59:59, add one second to obtain une more day
            date_to = self.date_to.replace(hour=23, minute=59, second=59) + relativedelta(seconds=1)
            self.number_of_days_calendar = (date_to - date_from).days
        else:
            self.number_of_days_calendar = 0

    # -- Inicio Sobrescribirá métodos para implementar asignaciones por contrato

    @api.constrains('state', 'number_of_days', 'holiday_status_id')
    def _check_validity(self):
        '''
        Overwrite method from add contract_id to domain filter
        '''
        mapped_days = self.mapped('holiday_status_id').get_employees_days(self.mapped('employee_id').ids, self.mapped('contract_id').ids)
        for holiday in self:
            if not holiday.employee_id or holiday.holiday_status_id.allocation_validation_type == 'no':
                continue
            leave_days = mapped_days[holiday.employee_id.id][holiday.contract_id.id][holiday.holiday_status_id.id]
            if float_compare(leave_days['remaining_leaves'], 0, precision_digits=2) == -1 or float_compare(leave_days['virtual_remaining_leaves'], 0, precision_digits=2) == -1:
                raise ValidationError(_('El número de tiempo libre restante no es suficiente para este tipo de tiempo libre.\n'
                                        'Por favor, verifique también el tiempo libre en espera de validación.'))
    # -- Fin Sobrescribirá


class HolidaysType(models.Model):
    _inherit = "hr.leave.type"

    # -- Inicio Sobrescribirá métodos para implementar asignaciones por contrato
    def get_employees_days(self, employee_ids, contract_ids):
        '''
        Overwrite method from add contract_id
        '''

        result = {
            employee_id: {
                contract_id: {
                    leave_type.id: {
                        'max_leaves': 0,
                        'leaves_taken': 0,
                        'remaining_leaves': 0,
                        'virtual_remaining_leaves': 0,
                        'virtual_leaves_taken': 0,
                    } for leave_type in self
                } for contract_id in contract_ids
            } for employee_id in employee_ids
        }

        requests = self.env['hr.leave'].search([
            ('employee_id', 'in', employee_ids),
            ('state', 'in', ['confirm', 'validate1', 'validate']),
            ('holiday_status_id', 'in', self.ids),
            ('contract_id', 'in', contract_ids)
        ])

        allocations = self.env['hr.leave.allocation'].search([
            ('employee_id', 'in', employee_ids),
            ('state', 'in', ['confirm', 'validate']),
            ('holiday_status_id', 'in', self.ids),
            ('contract_id', 'in', contract_ids)
        ])

        for request in requests:
            status_dict = result[request.employee_id.id][request.contract_id.id][request.holiday_status_id.id]
            status_dict['virtual_remaining_leaves'] -= (request.number_of_hours 
                                                        if request.leave_type_request_unit == 'hour'
                                                        else request.number_of_days)
            status_dict['virtual_leaves_taken'] += (request.number_of_hours 
                                                    if request.leave_type_request_unit == 'hour'
                                                    else request.number_of_days)
            if request.state == 'validate':
                status_dict['leaves_taken'] += (request.number_of_hours 
                                                if request.leave_type_request_unit == 'hour'
                                                else request.number_of_days)
                status_dict['remaining_leaves'] -= (request.number_of_hours 
                                                    if request.leave_type_request_unit == 'hour'
                                                    else request.number_of_days)

        for allocation in allocations.sudo():
            status_dict = result[allocation.employee_id.id][allocation.contract_id.id][allocation.holiday_status_id.id]
            if allocation.state == 'validate':
                # note: add only validated allocation even for the virtual
                # count; otherwise pending then refused allocation allow
                # the employee to create more leaves than possible
                status_dict['virtual_remaining_leaves'] += (allocation.number_of_hours 
                                                            if allocation.type_request_unit == 'hour'
                                                            else allocation.number_of_days)
                status_dict['max_leaves'] += (allocation.number_of_hours 
                                              if allocation.type_request_unit == 'hour'
                                              else allocation.number_of_days)
                status_dict['remaining_leaves'] += (allocation.number_of_hours 
                                                    if allocation.type_request_unit == 'hour'
                                                    else allocation.number_of_days)

        return result

    def _get_contextual_contract_id(self):
        if 'contract_id' in self._context:
            contract_id = self._context['contract_id']
        # elif 'default_employee_id' in self._context:
        #     employee_id = self._context['default_employee_id']
        else:
            contract_id = self.env.user.employee_id.contract_id.id
        return contract_id

    @api.depends_context('employee_id', 'default_employee_id')
    def _compute_leaves(self):
        '''
        Overwrite method from add contract_id
        '''
        data_days = {}
        employee_id = self.env['hr.employee']._get_contextual_employee().id
        contract_id = self._get_contextual_contract_id()

        if employee_id:
            data_days = self.get_employees_days([employee_id], [contract_id])[employee_id][contract_id]

        for holiday_status in self:
            result = data_days.get(holiday_status.id, {})
            holiday_status.max_leaves = result.get('max_leaves', 0)
            holiday_status.leaves_taken = result.get('leaves_taken', 0)
            # holiday_status.remaining_leaves = result.get('remaining_leaves', 0)
            holiday_status.virtual_remaining_leaves = result.get('virtual_remaining_leaves', 0)
            # holiday_status.virtual_leaves_taken = result.get('virtual_leaves_taken', 0)
    # -- Fin Sobrescribirá


class LeaveReport(models.Model):
    _inherit = "hr.leave.report"

    contract_id = fields.Many2one('hr.contract', string='Contrato', readonly=True)

    # -- Inicio Sobrescribirá métodos para implementar asignaciones por contrato

    # def init(self):
    #     """
    #     Overwrite method from add contract_id
    #     """
    #     tools.drop_view_if_exists(self._cr, 'hr_leave_report')

    #     self._cr.execute("""
    #         CREATE or REPLACE view hr_leave_report as (
    #             SELECT row_number() over(ORDER BY leaves.employee_id) as id,
    #                 leaves.employee_id as employee_id,
    #                 leaves.name as name,
    #                 leaves.contract_id as contract_id,
    #                 leaves.number_of_days as number_of_days,
    #                 leaves.leave_type as leave_type,
    #                 leaves.category_id as category_id,
    #                 leaves.department_id as department_id,
    #                 leaves.holiday_status_id as holiday_status_id,
    #                 leaves.state as state,
    #                 leaves.leave_type as holiday_type,
    #                 leaves.date_from as date_from,
    #                 leaves.date_to as date_to,
    #                 leaves.payslip_status as payslip_status
    #             FROM (
    #                 SELECT
    #                     allocation.employee_id as employee_id,
    #                     allocation.contract_id as contract_id,
    #                     --allocation.private_name as name,
    #                     allocation.number_of_days as number_of_days,
    #                     --allocation.category_id as category_id,
    #                     allocation.department_id as department_id,
    #                     allocation.holiday_status_id as holiday_status_id,
    #                     allocation.state as state,
    #                     --allocation.holiday_type,
    #                     null as date_from,
    #                     null as date_to,
    #                     FALSE as payslip_status,
    #                     'allocation' as leave_type
    #                 FROM
    #                     hr_leave_allocation as allocation
    #             UNION ALL
    #                 SELECT
    #                     --request.employee_id as employee_id,
    #                     request.contract_id as contract_id,
    #                     --request.private_name as name,
    #                     (request.number_of_days * -1) as number_of_days,
    #                     --request.category_id as category_id,
    #                     request.department_id as department_id,
    #                     request.holiday_status_id as holiday_status_id,
    #                     request.state as state,
    #                     --request.holiday_type,
    #                     request.date_from as date_from,
    #                     request.date_to as date_to,
    #                     request.state::boolean as payslip_status,
    #                     'request' as leave_type
    #             FROM
    #                 hr_leave as request) leaves
    #         );
    #     """)

    @api.model
    def action_time_off_analysis(self):
        '''
        Overwrite method from add contract_id
        '''
        domain = [('holiday_type', '=', 'employee')]

        if self.env.context.get('active_ids'):
            # Obtener contratos de los empleados con los ids obtenidos en context
            contract_ids = []
            employee_ids = self.env['hr.employee'].search([('id', 'in', tuple(self.env.context.get('active_ids', [])))])
            for employee_id in employee_ids:
                contract_ids.append(employee_id.contract_id.id)

            domain = Domain.AND([
                domain,
                [('employee_id', 'in', self.env.context.get('active_ids', [])), ('contract_id', 'in', contract_ids)]
            ])

        return {
            'name': _('Time Off Analysis'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.leave.report',
            'view_mode': 'tree,form,pivot',
            'search_view_id': self.env.ref('hr_holidays.view_hr_holidays_filter_report').id,
            'domain': domain,
            'context': {
                'search_default_group_type': True,
                'search_default_year': True
            }
        }
    # -- Fin Sobrescribirá
