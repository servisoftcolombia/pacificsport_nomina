from odoo import fields, models


class HrPayslipRunCo(models.Model):
    _inherit = "hr.payslip.run"

    liquidar_por = fields.Selection(
        selection=[
            ("nomina", "Nomina"),
            ("prima", "Prima"),
            ("cesantias", "Cesantias"),
            ("intereses_cesantias", "Intereses cesantias"),
            ("vacaciones", "Vacaciones"),
            ("definitiva", "Definitiva"),
        ],
        string="Liquidacion",
        default="nomina",
    )

    def generate_payslips(self, version_ids=None, employee_ids=None):
        return super(HrPayslipRunCo, self.with_context(default_liquidar_por=self.liquidar_por or "nomina")).generate_payslips(
            version_ids=version_ids,
            employee_ids=employee_ids,
        )

    def create_other_entries_from_contract(self):
        for payslip in self.slip_ids.filtered(lambda slip: slip.state != "cancel"):
            payslip.create_other_entries_from_contract()
        return False

    def regenerate_move_selection(self):
        """
        This model generate a wizard to select the move to regenerate in payslip run
        """
        return {
            "name": ("Selección regenerar asientos"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "view_type": "form",
            "res_model": "select.regenerate.move.wizard",
            "target": "new",
            "view_id": self.env.ref("l10n_co_payroll.select_regenerate_move_wizard_view_form").id,
            "context": self.env.context,
        }
