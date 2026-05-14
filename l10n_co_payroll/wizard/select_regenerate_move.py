from odoo import fields, models
import logging

_logger = logging.getLogger(__name__)


class SelectRegenerateMoveWizard(models.TransientModel):
    _name = "select.regenerate.move.wizard"
    _description = "Select move to regenerate in payslip"

    regenerate_move = fields.Boolean(string='Regenerar asiento contable', default=True)
    regenerate_move_pago = fields.Boolean(string='Regenerar asiento de pago', default=True)
    regenerate_third_move = fields.Boolean(string='Regenerar asiento de pago a terceros', default=False)

    def regenerate_move_selection(self):
        """
        This wizard sends the selected regeneration flags in context.
        """
        model = self.env.context.get('active_model')
        slips_group = []
        if model == 'hr.payslip':
            payslips = self.env[model].browse(self.env.context.get('active_ids'))
            slips_group.append(payslips)
        else:
            for payslip_run_id in self.env.context.get('active_ids'):
                payslips = self.env['hr.payslip'].search([('payslip_run_id', '=', payslip_run_id)])
                slips_group.append(payslips)

        ctx = {
            'regenerate_move': 'regenerate' if self.regenerate_move else 'no_regenerate',
            'regenerate_move_pago': 'regenerate' if self.regenerate_move_pago else 'no_regenerate',
            'regenerate_third_move': 'regenerate' if self.regenerate_third_move else 'no_regenerate',
        }
        for slips in slips_group:
            slips.with_context(ctx).action_regenerar_asiento()
        return {"type": "ir.actions.act_window_close"}
