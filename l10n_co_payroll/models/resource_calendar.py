# -*- encoding: utf-8 -*-
from collections import defaultdict
import math
from datetime import datetime, time, timedelta
from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, DAILY, WEEKLY
from functools import partial
from itertools import chain
from pytz import timezone, utc

from odoo import api, fields, models, _
from odoo.addons.base.models.res_partner import _tz_get
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools.float_utils import float_round

from odoo.tools import date_utils, float_utils

from odoo.addons.resource.models.resource_calendar import Intervals, float_to_time

import logging

_logger = logging.getLogger(__name__)


class ResCalendar(models.Model):
    _inherit = "resource.calendar"

    start_day_period = fields.Selection(string='Start day period',
                                        selection=[('morning', 'Morning'), ('afternoon', 'Afternoon')],
                                        compute='_compute_start_day_period')

    def _compute_start_day_period(self):
        for record in self:
            if record.attendance_ids and len(record.attendance_ids) > 0:
                record.start_day_period = record.attendance_ids.sorted(key=lambda r: r.sequence)[0].day_period
            else:
                record.start_day_period = None

    def _attendance_intervals_batch(self, start_dt, end_dt, resources=None, domain=None, tz=None, lunch=False):
        return super()._attendance_intervals_batch(
            start_dt,
            end_dt,
            resources=resources,
            domain=domain,
            tz=tz,
            lunch=lunch,
        )

    def _leave_intervals(self, start_dt, end_dt, resource=None, domain=None, tz=None):
        """ Return the leave intervals in the given datetime range.
            The returned intervals are expressed in the calendar's timezone.
        """
        assert start_dt.tzinfo and end_dt.tzinfo
        self.ensure_one()

        # for the computation, express all datetimes in UTC
        resource_ids = [resource.id, False] if resource else [False]
        if domain is None:
            domain = [('time_type', '=', 'leave')]
        domain = domain + [
            ('calendar_id', '=', self.id),
            ('resource_id', 'in', resource_ids),
            ('date_from', '<=', fields.Datetime.to_string(end_dt.astimezone(utc).replace(tzinfo=None))),
            ('date_to', '>=', fields.Datetime.to_string(start_dt.astimezone(utc).replace(tzinfo=None))),
            ('unpaid_calendar', '=', True),
        ]

        # retrieve leave intervals in (start_dt, end_dt)
        tz = timezone((resource or self).tz)
        start_dt = start_dt.astimezone(tz)
        end_dt = end_dt.astimezone(tz)
        result = []
        for leave in self.env['resource.calendar.leaves'].search(domain):
            dt0 = fields.Datetime.to_datetime(leave.date_from)
            dt1 = fields.Datetime.to_datetime(leave.date_to)
            if dt0 and not dt0.tzinfo:
                dt0 = utc.localize(dt0)
            if dt1 and not dt1.tzinfo:
                dt1 = utc.localize(dt1)
            dt0 = dt0.astimezone(tz)
            dt1 = dt1.astimezone(tz)
            result.append((max(start_dt, dt0), min(end_dt, dt1), leave))

        return Intervals(result)


class ResourceCalendarAttendance(models.Model):
    _inherit = 'resource.calendar.attendance'

    def create(self, values):
        for value in values:
            value.update({"work_entry_type_id": False})
        return super(ResourceCalendarAttendance, self).create(values)

    @api.onchange('hour_from', 'hour_to')
    def _onchange_hours(self):
        '''
            Overwrite function to permit 24 hour, because whit 23.99, loss une minute un the calculation
        '''
        # avoid negative or after midnight
        self.hour_from = min(self.hour_from, 24)
        self.hour_from = max(self.hour_from, 0.0)
        self.hour_to = min(self.hour_to, 24)
        self.hour_to = max(self.hour_to, 0.0)

        # avoid wrong order
        self.hour_to = max(self.hour_to, self.hour_from)


class HRCalendarLeaves(models.Model):

    _inherit = 'resource.calendar.leaves'

    unpaid_calendar = fields.Boolean(
        related="holiday_id.holiday_status_id.unpaid",
        copy=False
    )
