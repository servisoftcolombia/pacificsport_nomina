from odoo import SUPERUSER_ID, api
from odoo.addons.l10n_co_payroll.hooks import ensure_payroll_template


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    ensure_payroll_template(env)
