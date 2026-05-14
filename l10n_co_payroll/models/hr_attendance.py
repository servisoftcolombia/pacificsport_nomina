from odoo import models


class HrAttendanceGantt(models.Model):
    _inherit = "hr.attendance"

    def _gantt_progress_bar_employee_ids(self, res_ids, start, stop):
        """
        Resulting display is worked hours / expected worked hours
        """
        values = {}
        worked_hours_group = self._read_group([('employee_id', 'in', res_ids),
                                               ('check_in', '>=', start),
                                               ('check_out', '<=', stop)],
                                              groupby=['employee_id'],
                                              aggregates=['worked_hours:sum'])
        employee_data = {emp.id: worked_hours for emp, worked_hours in worked_hours_group}
        employees = self.env['hr.employee'].browse(res_ids)
        for employee in employees:
            intervals = employee._get_expected_attendances(start, stop)
            total_hours = sum((interval[1] - interval[0]).total_seconds() for interval in intervals) / 3600
            # Retrieve expected attendance for that employee
            values[employee.id] = {
                'value': employee_data.get(employee.id, 0),
                'max_value': total_hours,
            }

        return values
