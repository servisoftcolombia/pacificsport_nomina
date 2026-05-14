from odoo import api, fields, models


class PaymentMean(models.Model):
    _name = 'l10n_co_payroll.payment_mean'
    _description = 'Medios de pago DIAN para nómina'

    name = fields.Char('Nombre', required=True)
    codigo_dian = fields.Char(string='Código DIAN', required=True)
    nombre_tecnico_dian = fields.Char(string='Medio', required=True)

    _codigo_dian_unique = models.Constraint(
        'unique(codigo_dian)',
        'El código DIAN del medio de pago debe ser único.',
    )

    @api.model
    def _get_default_payment_mean(self):
        self.env.cr.execute("SELECT to_regclass(%s)", (self._table,))
        if not self.env.cr.fetchone()[0]:
            return False
        return self.search([('codigo_dian', '=', '10')], limit=1)

    def name_get(self):
        return [(record.id, record.nombre_tecnico_dian) for record in self]
