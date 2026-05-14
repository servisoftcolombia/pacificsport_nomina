from odoo import models, fields


class ResPartnerBank(models.Model):
    _inherit = "res.partner.bank"
    tipo_cuenta = fields.Selection(string="Tipo cuenta",
                                   selection=[
                                       ("ahorros","Ahorros"),
                                       ("corriente","Corriente"),
                                       ("ca", "Cuenta de ahorros"),
                                       ("cc", "Cuenta de corriente")
                                   ],
                                   default="ca")

