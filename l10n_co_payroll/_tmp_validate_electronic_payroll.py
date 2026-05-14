import base64
import calendar
from datetime import date

import odoo
from dateutil.relativedelta import relativedelta
from OpenSSL import crypto
from odoo import SUPERUSER_ID, api, fields
from odoo.modules.registry import Registry
from odoo.service import server as odoo_server
from odoo.tools import config


DB_NAME = "DEMO"
DB_HOST = "db"
DB_PASSWORD = "odoo"
CONFIG_FILE = "/etc/odoo/odoo.conf"
env = None

VALIDATION_TRACE_VARIABLES = {
    2025: {
        "smlv": 1423500,
        "aux_trans": 200000,
        "valor_uvt": 49799,
    },
    2026: {
        "smlv": 1750905,
        "aux_trans": 249095,
        "valor_uvt": 53343,
    },
}


class _RollbackTest(Exception):
    pass


def _month_period(reference_date):
    last_day = calendar.monthrange(reference_date.year, reference_date.month)[1]
    return reference_date.replace(day=1), reference_date.replace(day=last_day)


def _find_validation_period(reference_date, min_months_back=3, max_months_back=24):
    for offset in range(min_months_back, max_months_back + 1):
        target = reference_date - relativedelta(months=offset)
        period_start, period_end = _month_period(target)
        existing = env["hr.payslip"].search_count(
            [
                ("date_from", "<=", period_end),
                ("date_to", ">=", period_start),
                ("state", "in", ("validated", "paid")),
            ]
        )
        if not existing:
            return period_start, period_end, offset
    fallback = reference_date - relativedelta(months=min_months_back)
    period_start, period_end = _month_period(fallback)
    return period_start, period_end, min_months_back


def _get_struct(contract):
    return (
        contract.structure_id
        or contract.structure_type_id.default_struct_id
        or env["hr.payroll.structure"].search(
            [("company_id", "in", [False, contract.company_id.id])],
            limit=1,
        )
    )


def _get_contract_for_period(period_start, period_end):
    contracts = env["hr.version"].search(
        [
            ("employee_id", "!=", False),
            ("contract_date_start", "!=", False),
        ],
        order="id",
    )
    for contract in contracts:
        start_date = contract._l10n_co_payroll_get_start_date() or contract.contract_date_start or contract.date_start
        end_date = contract._l10n_co_payroll_get_end_date() or contract.contract_date_end or contract.date_end
        if not start_date or start_date > period_end:
            continue
        if end_date and end_date < period_start:
            continue
        overlapping = env["hr.payslip"].search_count(
            [
                ("employee_id", "=", contract.employee_id.id),
                ("contract_id", "=", contract.id),
                ("date_from", "<=", period_end),
                ("date_to", ">=", period_start),
                ("state", "!=", "cancel"),
            ]
        )
        if not overlapping:
            return contract
    return env["hr.version"]


def _ensure_validation_trace_variable(reference_date):
    trace_variable = env["traza.variable"].search(
        [
            ("fecha_desde", "<=", reference_date),
            ("fecha_hasta", ">=", reference_date),
        ],
        limit=1,
    )
    if trace_variable:
        return trace_variable

    values = VALIDATION_TRACE_VARIABLES.get(reference_date.year)
    if not values:
        raise RuntimeError(f"Missing validation trace variable defaults for year {reference_date.year}")

    trace_variable = env["traza.variable"].create(
        {
            "fecha_desde": date(reference_date.year, 1, 1),
            "fecha_hasta": date(reference_date.year, 12, 31),
            "smlv": values["smlv"],
            "smilv": values["smlv"] * 13,
            "aux_trans": values["aux_trans"],
            "valor_uvt": values["valor_uvt"],
        }
    )
    print(
        "TRACE_VARIABLE_TEMP",
        trace_variable.id,
        trace_variable.fecha_desde,
        trace_variable.fecha_hasta,
        trace_variable.smlv,
        trace_variable.aux_trans,
        trace_variable.valor_uvt,
    )
    return trace_variable


def _find_identification_type(code):
    return env["l10n_latam.identification.type"].search(
        [("l10n_co_document_code", "=", code)],
        limit=1,
    )


def _format_valid_nit(number):
    coefficients = [71, 67, 59, 53, 47, 43, 41, 37, 29, 23, 19, 17, 13, 7, 3]
    digits = [int(digit) for digit in str(number)]
    digits = [0] * (len(coefficients) - len(digits)) + digits
    total = sum(digit * coefficient for digit, coefficient in zip(digits, coefficients))
    remainder = total % 11
    verification_digit = remainder if remainder < 2 else 11 - remainder
    return f"{number}-{verification_digit}"


def _get_co_location():
    country = env["res.country"].search([("code", "=", "CO")], limit=1)
    state = env["res.country.state"].search(
        [("country_id", "=", country.id)],
        order="id",
        limit=1,
    )
    city = env["res.city"].search([("state_id", "=", state.id)], order="id", limit=1)
    return country, state, city


def _ensure_company_partner(company):
    country, state, city = _get_co_location()
    partner = company.partner_id
    if not partner:
        partner = env["res.partner"].create(
            {
                "name": company.name,
                "company_type": "company",
                "is_company": True,
            }
        )
        company.partner_id = partner

    values = {
        "name": company.name,
        "company_type": "company",
        "is_company": True,
        "street": partner.street or "Calle 100 # 10-10",
        "country_id": country.id,
        "state_id": state.id,
        "city_id": city.id,
        "email": partner.email or f"nomina+company{company.id}@example.com",
    }
    identification_type = _find_identification_type("rut")
    if identification_type:
        values["l10n_latam_identification_type_id"] = identification_type.id
    values["vat"] = _format_valid_nit(900000000 + company.id)
    if "l10n_co_edi_commercial_name" in partner._fields:
        values["l10n_co_edi_commercial_name"] = company.name
    partner.write(values)
    print(
        "COMPANY_PARTNER_TEMP",
        f"company={company.id}",
        f"partner={partner.id}",
        f"document={partner.fe_tipo_documento}/{partner.fe_nit}",
        f"dv={partner.fe_digito_verificacion}",
    )
    return partner


def _ensure_employee_home_partner(contract):
    employee = contract.employee_id
    country, state, city = _get_co_location()
    partner = employee._l10n_co_payroll_get_home_partner()
    default_name = employee.name if employee.name and " " in employee.name else f"Empleado {employee.id} Prueba"
    values = {
        "name": default_name,
        "company_type": "person",
        "street": (partner.street if partner else False) or "Carrera 10 # 20-30",
        "country_id": country.id,
        "state_id": state.id,
        "city_id": city.id,
        "email": (partner.email if partner else False) or f"empleado.{employee.id}@example.com",
        "fe_habilitada": True,
    }
    identification_type = _find_identification_type("national_citizen_id")
    if identification_type:
        values["l10n_latam_identification_type_id"] = identification_type.id
    if not partner:
        values["vat"] = str(100000000 + employee.id)
        partner = env["res.partner"].create(values)
        employee.address_home_id = partner
    else:
        if not partner.vat:
            values["vat"] = str(100000000 + employee.id)
        partner.write(values)
        if not employee.address_home_id:
            employee.address_home_id = partner

    print(
        "HOME_PARTNER_TEMP",
        f"employee={employee.id}",
        f"partner={partner.id}",
        f"document={partner.fe_tipo_documento}/{partner.fe_nit}",
    )
    return partner


def _ensure_department_and_job(contract):
    employee = contract.employee_id
    department = employee.department_id or env["hr.department"].search([("name", "=", "TMP Payroll")], limit=1)
    if not department:
        department = env["hr.department"].create({"name": "TMP Payroll"})

    job = employee.job_id or env["hr.job"].search([("name", "=", "TMP Payroll Analyst")], limit=1)
    if not job:
        job_values = {"name": "TMP Payroll Analyst"}
        if "company_id" in env["hr.job"]._fields:
            job_values["company_id"] = contract.company_id.id
        job = env["hr.job"].create(job_values)

    employee.write(
        {
            "department_id": department.id,
            "job_id": job.id,
        }
    )
    contract_values = {}
    if "department_id" in contract._fields and not contract.department_id:
        contract_values["department_id"] = department.id
    if "job_id" in contract._fields and not contract.job_id:
        contract_values["job_id"] = job.id
    if contract_values:
        contract.write(contract_values)
    print(
        "EMPLOYEE_ORG_TEMP",
        f"employee={employee.id}",
        f"department={department.id}",
        f"job={job.id}",
    )


def _ensure_partner(name):
    partner = env["res.partner"].search([("name", "=", name)], limit=1)
    if partner:
        return partner
    return env["res.partner"].create(
        {
            "name": name,
            "company_type": "company",
            "is_company": True,
        }
    )


def _ensure_affiliations(company, employee):
    partners = {
        "eps": _ensure_partner("TMP EPS"),
        "fp": _ensure_partner("TMP AFP"),
        "fc": _ensure_partner("TMP FC"),
        "ccf": _ensure_partner("TMP CCF"),
        "arl": _ensure_partner("TMP ARL"),
        "icbf": _ensure_partner("TMP ICBF"),
        "sena": _ensure_partner("TMP SENA"),
        "dian": _ensure_partner("TMP DIAN"),
    }
    company.write(
        {
            "ccf_id": partners["ccf"].id,
            "arl_id": partners["arl"].id,
            "icbf_id": partners["icbf"].id,
            "sena_id": partners["sena"].id,
            "dian_id": partners["dian"].id,
        }
    )
    employee.write(
        {
            "eps_id": partners["eps"].id,
            "fp_id": partners["fp"].id,
            "fc_id": partners["fc"].id,
            "ccf_id": partners["ccf"].id,
            "nivel_arl": employee.nivel_arl or "1",
        }
    )
    print(
        "AFFILIATIONS_TEMP",
        f"company={company.id}",
        f"employee={employee.id}",
        f"partners={ {key: value.id for key, value in partners.items()} }",
    )


def _ensure_employee_bank_account(employee, home_partner):
    bank = env["res.bank"].search([("bic", "!=", False)], limit=1)
    if not bank:
        bank = env["res.bank"].create({"name": "TMP Bank", "bic": "0123"})

    partner_bank = env["res.partner.bank"].search([("partner_id", "=", home_partner.id)], limit=1)
    values = {
        "partner_id": home_partner.id,
        "bank_id": bank.id,
        "acc_number": "00012345678901234",
        "tipo_cuenta": "ahorros",
    }
    if partner_bank:
        partner_bank.write(values)
    else:
        partner_bank = env["res.partner.bank"].create(values)

    employee_values = {}
    if "bank_account_ids" in employee._fields:
        employee_values["bank_account_ids"] = [(6, 0, [partner_bank.id])]
    if employee_values:
        employee.write(employee_values)
    print(
        "EMPLOYEE_BANK_TEMP",
        f"employee={employee.id}",
        f"partner={home_partner.id}",
        f"bank_account={partner_bank.id}",
        f"tipo_cuenta={partner_bank.tipo_cuenta}",
        f"acc_number={partner_bank.acc_number}",
    )
    return partner_bank


def _ensure_incapacity_function(company):
    function = company.pcts_incapacidades or env.ref("l10n_co_payroll.ft_pcts_incapacidades", raise_if_not_found=False)
    if not function:
        function = env["funcion.trozo"].create(
            {
                "nombre": "TMP Pcts Incapacidades",
                "funcion_trozo_detalle_ids": [
                    (0, 0, {"desde": 1, "hasta": 2, "valor_inicial": 0.6667, "valor_adicional": 0.0}),
                    (0, 0, {"desde": 3, "hasta": 90, "valor_inicial": 0.6667, "valor_adicional": 0.0}),
                ],
            }
        )
    company.pcts_incapacidades = function
    print("PCTS_INCAP_TEMP", f"company={company.id}", f"function={function.id}")
    return function


def _create_sequence(name, code, company):
    return env["ir.sequence"].create(
        {
            "name": name,
            "code": code,
            "implementation": "no_gap",
            "prefix": "",
            "padding": 1,
            "number_next": 1,
            "number_increment": 1,
            "company_id": company.id,
        }
    )


def _build_temp_pkcs12(password):
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)

    certificate = crypto.X509()
    certificate.get_subject().CN = "TMP L10N CO Payroll"
    certificate.set_serial_number(1)
    certificate.gmtime_adj_notBefore(0)
    certificate.gmtime_adj_notAfter(365 * 24 * 60 * 60)
    certificate.set_issuer(certificate.get_subject())
    certificate.set_pubkey(key)
    certificate.sign(key, "sha256")

    pkcs12 = crypto.PKCS12()
    pkcs12.set_privatekey(key)
    pkcs12.set_certificate(certificate)
    return pkcs12.export(passphrase=password.encode())


def _ensure_ne_company_config(company, period_start):
    nie_sequence = _create_sequence(
        f"TMP NIE {company.id}",
        f"tmp.l10n_co_payroll.nie.{company.id}.{period_start.isoformat()}",
        company,
    )
    nia_sequence = _create_sequence(
        f"TMP NIA {company.id}",
        f"tmp.l10n_co_payroll.nia.{company.id}.{period_start.isoformat()}",
        company,
    )
    certificate_password = "tmp-pass"
    certificate = base64.b64encode(_build_temp_pkcs12(certificate_password)).decode()
    policy_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    company.write(
        {
            "ne_habilitada_compania": True,
            "nomina_electronica_id": company.nomina_electronica_id or f"TMP-NE-{company.id}",
            "ne_tipo_ambiente": "2",
            "ne_test_set_id": company.ne_test_set_id or "TMP-TEST-SET",
            "ne_software_id": f"TMP-SOFT-{company.id}",
            "view_ne_software_pin": "12345",
            "ne_certificado": certificate,
            "view_ne_certificado_password": certificate_password,
            "ne_url_politica_firma": "https://example.com/politica-firma-ne.pdf",
            "ne_archivo_politica_firma": base64.b64encode(policy_bytes).decode(),
            "ne_descripcion_politica_firma": "Politica temporal para validacion NE",
            "secuencia_nomina_individual_electronica": nie_sequence.id,
            "secuencia_nomina_individual_ajuste": nia_sequence.id,
            "ne_nomina_email": f"nomina+company{company.id}@example.com",
            "fecha_inicio_reporte_nominas_electronicas": date(period_start.year, 1, 1),
        }
    )
    print(
        "COMPANY_NE_TEMP",
        f"company={company.id}",
        f"nie_sequence={nie_sequence.id}",
        f"nia_sequence={nia_sequence.id}",
        f"software_id={company.ne_software_id}",
        f"test_set={company.ne_test_set_id}",
    )


def _prepare_environment(contract, period_start, period_end):
    company = contract.company_id
    _ensure_validation_trace_variable(period_end)
    _ensure_company_partner(company)
    home_partner = _ensure_employee_home_partner(contract)
    _ensure_department_and_job(contract)
    _ensure_affiliations(company, contract.employee_id)
    _ensure_employee_bank_account(contract.employee_id, home_partner)
    _ensure_incapacity_function(company)
    _ensure_ne_company_config(company, period_start)
    return company, home_partner


def _create_payslip(contract, period_start, period_end):
    struct = _get_struct(contract)
    if not struct:
        raise RuntimeError(f"Missing payroll structure for contract {contract.id}")

    payslip = env["hr.payslip"].create(
        {
            "name": f"TMP nomina {contract.employee_id.name}",
            "employee_id": contract.employee_id.id,
            "version_id": contract.id,
            "company_id": contract.company_id.id,
            "struct_id": struct.id,
            "date_from": period_start,
            "date_to": period_end,
            "liquidar_por": "nomina",
        }
    )
    payslip._onchange_employee()
    payslip.compute_sheet()
    if hasattr(payslip, "validate_info_electronic_payslip"):
        payslip.validate_info_electronic_payslip()
    payslip.write({"state": "validated"})
    print(
        "PAYSLIP_TEMP",
        f"id={payslip.id}",
        f"employee={payslip.employee_id.id}",
        f"contract={payslip.contract_id.id}",
        f"payment_mean={getattr(payslip.payment_mean_id, 'codigo_dian', False)}",
        f"lines={len(payslip.line_ids)}",
    )
    return payslip


def _assert_electronic_document(prefix, electronic):
    document = electronic.electronic_document_id
    xml_bytes = base64.b64decode(electronic.xml or b"") if electronic.xml else b""
    print(
        prefix,
        f"electronic={electronic.id}",
        f"tipo_nomina={electronic.tipo_nomina}",
        f"ajuste={electronic.tipo_ajuste}",
        f"consecutivo={electronic.consecutivo}",
        f"cune={bool(electronic.cune)}",
        f"xml={len(xml_bytes)}",
        f"document={document.id}",
        f"estado={document.estado}",
        f"xml_firmado={bool(document.peticion_xml_firmada)}",
        f"zip={bool(document.peticion_xml_comprimida)}",
        f"filename={document.nombre_archivo_xml}",
    )
    if not electronic.xml:
        raise AssertionError(f"{prefix} missing electronic xml")
    if not electronic.cune:
        raise AssertionError(f"{prefix} missing CUNE")
    if not document:
        raise AssertionError(f"{prefix} missing electronic document")
    if document.estado != "preparado":
        raise AssertionError(f"{prefix} unexpected document state {document.estado}")
    if not document.peticion_xml_firmada:
        raise AssertionError(f"{prefix} missing signed xml")
    if not document.peticion_xml_comprimida:
        raise AssertionError(f"{prefix} missing zipped xml")


def _validate_direct_flow(contract, period_start, period_end):
    try:
        with env.cr.savepoint():
            company, home_partner = _prepare_environment(contract, period_start, period_end)
            payslip = _create_payslip(contract, period_start, period_end)
            electronic = env["hr.payslip.electronic"].create(
                {
                    "state": "draft",
                    "company_id": company.id,
                    "employee_id": contract.employee_id.id,
                    "ne_sucursal": home_partner.id,
                    "date_start": period_start,
                    "date_end": period_end,
                    "tipo_nomina": "1",
                    "tipo_ajuste": "0",
                    "payment_mean_id": payslip.payment_mean_id.id,
                }
            )
            payslip.write({"payslip_electronic_id": electronic.id})
            electronic.creacion_xml_nomina_dian()
            _assert_electronic_document("DIRECT_OK", electronic)
            raise _RollbackTest
    except _RollbackTest:
        return
    except Exception as err:
        print(f"DIRECT_ERROR {type(err).__name__}: {err}")


def _validate_cron_and_regeneration(contract, period_start, period_end, months_back):
    try:
        with env.cr.savepoint():
            company, _home_partner = _prepare_environment(contract, period_start, period_end)
            payslip = _create_payslip(contract, period_start, period_end)
            env.flush_all()
            env["hr.payslip.electronic"].cron_creacion_xml(months=months_back, company_id=company)
            electronic = env["hr.payslip.electronic"].search(
                [
                    ("employee_id", "=", contract.employee_id.id),
                    ("date_start", "=", period_start),
                    ("date_end", "=", period_end),
                    ("company_id", "=", company.id),
                ],
                order="id desc",
                limit=1,
            )
            if not electronic:
                raise AssertionError("CRON did not create hr.payslip.electronic")
            payslip.invalidate_recordset()
            if payslip.payslip_electronic_id.id != electronic.id:
                raise AssertionError("CRON did not link payslip to electronic payroll")
            _assert_electronic_document("CRON_OK", electronic)

            original_document = electronic.electronic_document_id
            electronic.action_regenerar_xml()
            electronic.invalidate_recordset()
            if not electronic.electronic_document_id:
                raise AssertionError("REGEN missing regenerated document")
            if electronic.electronic_document_id.id == original_document.id:
                raise AssertionError("REGEN reused deleted document")
            _assert_electronic_document("REGEN_OK", electronic)
            raise _RollbackTest
    except _RollbackTest:
        return
    except Exception as err:
        print(f"CRON_ERROR {type(err).__name__}: {err}")


def main():
    global env

    config.parse_config(
        [
            "-c",
            CONFIG_FILE,
            "-d",
            DB_NAME,
            "--db_host",
            DB_HOST,
            "--db_password",
            DB_PASSWORD,
        ]
    )
    odoo_server.load_server_wide_modules()
    registry = Registry(DB_NAME)

    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        today = fields.Date.context_today(env.user)
        period_start, period_end, months_back = _find_validation_period(today)
        contract = _get_contract_for_period(period_start, period_end)

        print(
            "ELECTRONIC_CONTEXT",
            f"today={today}",
            f"period={period_start}/{period_end}",
            f"months_back={months_back}",
            f"contract={getattr(contract, 'id', False)}",
            f"employee={getattr(getattr(contract, 'employee_id', False), 'id', False)}",
            f"company={getattr(getattr(contract, 'company_id', False), 'id', False)}",
        )

        if not contract:
            print("ELECTRONIC_ERROR missing contract for validation period")
            cr.rollback()
            return

        _validate_direct_flow(contract, period_start, period_end)
        _validate_cron_and_regeneration(contract, period_start, period_end, months_back)
        cr.rollback()


if __name__ == "__main__":
    main()
