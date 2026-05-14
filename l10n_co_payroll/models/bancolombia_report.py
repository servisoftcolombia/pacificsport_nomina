# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

# from curses.ascii import US
from odoo import tools
from odoo import fields, models
import logging
US = "\x1f"  # ASCII 'Unit Separator' character

_logger = logging.getLogger(__name__)


class BancolombiaReport(models.Model):
    _name = "bancolombia.report"
    _auto = False
    _description = "Reporte bancolombia"

    dato = fields.Char(string='dato', readonly=True)

    def _query(self, with_clause='', fields={}, groupby='', from_clause=''):
        with_ = ("WITH %s" % with_clause) if with_clause else ""

        select_ = """
            with t_bancolombia as (
                select
                    ps.id as "id",
                    ps.company_id as "company_id",
                    move_payment.journal_id as "payment_journal_id",
                    '6' as "a",
                    rpad(coalesce(rp.fe_nit, ''),15,' ') as "b",
                    rpad(coalesce(ep.name, ''),30,' ') as "c",
                    lpad(coalesce(rb.bic, ''),9,'0') as "d",
                    lpad(coalesce(rpb.acc_number, ''),17,'0') as "e",
                    ' ' as "f",
                    lpad(
                        coalesce(
                            case when rpb.tipo_cuenta in ('corriente', 'cc') then '27'
                                 when rpb.tipo_cuenta in ('ahorros', 'ca') then '37'
                            end,
                            '00'
                        ),
                        2,
                        '0'
                    ) as "g",
                    coalesce(round(psl.total*100,0),0)::numeric as "amount_numeric",
                    lpad(coalesce(round(psl.total*100,0)::text, '0'),17,'0') as "h",
                    to_char(current_date,'yyyymmdd')::character(8) as "i",
                    rpad(coalesce(psr.name, ''),21,' ') as "j",
                    ' ' as "k",
                    '00000' as "l",
                    '               ' as "m",
                    rpad(coalesce(ep.work_email, ''),80,' ') as "n",
                    lpad('',15,' ') as "o",
                    lpad('',27,' ') as "p"
                from hr_payslip ps
                    left join (select slip_id, name, total from hr_payslip_line where code = 'NET' order by slip_id) psl on (ps.id = psl.slip_id)
                    left join account_move move_payment on (ps.move_id_pago = move_payment.id)
                    left join res_company co on (ps.company_id = co.id)
                    left join hr_employee ep on (ps.employee_id = ep.id)
                    left join res_partner rp on (ep.address_home_id = rp.id)
                    left join (
                        select distinct on (rpb.partner_id) rpb.partner_id, rpb.create_date, rpb.acc_number, rpb.bank_id, rpb.tipo_cuenta
                        from res_partner_bank rpb
                        order by rpb.partner_id, rpb.create_date
                    ) rpb on (rp.id = rpb.partner_id)
                    left join res_bank rb on (rpb.bank_id = rb.id)
                    inner join hr_payslip_run psr on (ps.payslip_run_id = psr.id and psr.id = 0000)
                where ps.state in ('done', 'validated', 'paid')
            ),
            t_encabezado_banco as (
                select
                    header_source.id as "id",
                    '1' as "a",
                    lpad(coalesce(rpc.fe_nit, ''),15,'0') as "b",
                    'I' as "c",
                    '               ' as "d",
                    '225' as "e",
                    'PAGO NOMIN' as "f",
                    to_char(current_date,'yyyymmdd')::character(8) as "g",
                    'HH' as "h",
                    to_char(current_date,'yyyymmdd')::character(8) as "i",
                    lpad(coalesce((select count(*)::text from t_bancolombia), '0'),6,'0') as "j",
                    '00000000000000000' as "k",
                    lpad(coalesce((select round(sum("amount_numeric"),0)::text from t_bancolombia), '0'),17,'0') as "l",
                    lpad(coalesce(company_bank.acc_number, ''),11,'0') as "m",
                    'D' as "n",
                    lpad('',149,' ') as "o"
                from
                    (
                        select distinct on (tb.company_id)
                            tb.id,
                            tb.company_id,
                            tb.payment_journal_id
                        from t_bancolombia tb
                        order by tb.company_id, tb.id
                    ) header_source
                    inner join res_company co on (co.id = header_source.company_id)
                    left join res_partner rpc on (co.partner_id = rpc.id)
                    left join lateral (
                        select rpb.acc_number
                        from account_journal aj
                            inner join res_partner_bank rpb on (aj.bank_account_id = rpb.id)
                        where aj.company_id = header_source.company_id
                        order by case when aj.id = header_source.payment_journal_id then 0 else 1 end, aj.id
                        limit 1
                    ) company_bank on true
            )
            select "id", concat("a","b","c","d","e","f","g","h","i","j","k","l","m","n","o") as dato from t_encabezado_banco
            union
            select "id", concat("a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p") as dato from t_bancolombia
            order by dato
        """


        for field in fields.values():
            select_ += field

        from_ = """
        """

        where_ = """
        """

        return select_

    def init(self):
        # self._table = sale_report
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Tomar la consulta
        query = """CREATE or REPLACE VIEW %s as (%s)""" % (self._table, self._query())
        # En el context se ha enviado el id del lote, se inserta en en la consulta
        ctx = dict(self.env.context)
        if 'lote' in ctx:
            query = query.replace("0000", str(ctx["lote"]))
        _logger.debug(query)
        self.env.cr.execute(query)
