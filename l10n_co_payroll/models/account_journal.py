from odoo import api, fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    journal_payroll = fields.Boolean(string='Diario de pago Nomina', help='Selecciónelo si es el diario de pagos de la nomina', default=False)
    default_debit_discount_id = fields.Many2one(
        'account.account',
        string='Cuenta Débito de Descuento',
        help='Cuenta usada por la compatibilidad contable de nómina para ajustes al débito.',
        domain=[('active', '=', True)],
    )
    default_credit_discount_id = fields.Many2one(
        'account.account',
        string='Cuenta Crédito de Descuento',
        help='Cuenta usada por la compatibilidad contable de nómina para ajustes al crédito.',
        domain=[('active', '=', True)],
    )
    severance_account_id = fields.Many2one(
        'account.account',
        string='Cuenta pago cesantias',
        help='Seleccione la cuenta de pago de cesantias',
        domain=[('active', '=', True)],
    )
    severance_interest_account_id = fields.Many2one(
        'account.account',
        string='Cuenta pago intereses de cesantias',
        help='Seleccione la cuenta de pago de intereses cesantias',
        domain=[('active', '=', True)],
    )
    service_bonus_account_id = fields.Many2one(
        'account.account',
        string='Cuenta pago prima de servicios',
        help='Seleccione la cuenta de pago de prima de servicios',
        domain=[('active', '=', True)],
    )
    vacations_account_id = fields.Many2one(
        'account.account',
        string='Cuenta pago de vacaciones',
        help='Seleccione la cuenta de pago de vacaciones',
        domain=[('active', '=', True)],
    )

    @api.onchange('default_account_id')
    def _onchange_l10n_co_payroll_default_account_id(self):
        for journal in self:
            if not journal.default_account_id:
                continue
            if not journal.default_debit_discount_id:
                journal.default_debit_discount_id = journal.default_account_id
            if not journal.default_credit_discount_id:
                journal.default_credit_discount_id = journal.default_account_id
