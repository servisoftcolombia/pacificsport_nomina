import json
from pathlib import Path

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.service import server as odoo_server
from odoo.tools import config


DB_NAME = "DEMO"
DB_HOST = "db"
DB_PASSWORD = "odoo"
CONFIG_FILE = "/etc/odoo/odoo.conf"
ADDON_PATH = Path(__file__).resolve().parent

DATASETS = {
    "category": ("hr_salary_rule_category_data.json", "category"),
    "work_entry_type": ("hr_work_entry_type_data.json", "entry"),
    "structure_type": ("hr_payroll_structure_type_data.json", "type"),
    "structure": ("hr_payroll_structure_data.json", "payroll"),
    "rule": ("hr_salary_rule_data.json", "rule"),
    "input": ("hr_payslip_input_type_data.json", "input"),
}

RULE_ACCOUNT_EXPECTATIONS = {
    "PRO_CES": {"administracion", "ventas", "produccion"},
    "PRO_VAC": {"administracion", "ventas", "produccion"},
    "PRO_PRI_SER": {"administracion", "ventas", "produccion"},
    "EPS_COM": {"administracion", "ventas", "produccion"},
    "SAL_TRA": {"administracion", "ventas", "produccion"},
}


class _RollbackTest(Exception):
    pass


def _load_expected_values(dataset_name, field_name):
    filename, key = DATASETS[dataset_name]
    with (ADDON_PATH / "data" / filename).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return {record[field_name] for record in payload[key] if record.get(field_name)}


def _assert_contains_all(label, expected_values, actual_values):
    missing_values = sorted(expected_values - actual_values)
    if missing_values:
        sample = ", ".join(missing_values[:10])
        raise AssertionError(f"{label} missing {len(missing_values)} values: {sample}")
    print(f"{label}_OK expected={len(expected_values)} actual={len(actual_values)}")


def _validate_rule_accounts(env, company):
    accounts = env["salary.rule.account"].search(
        [
            ("company_id", "=", company.id),
            ("regla_salarial.code", "in", list(RULE_ACCOUNT_EXPECTATIONS)),
        ]
    )
    coverage = {(account.regla_salarial.code, account.area_trabajo) for account in accounts}
    missing_pairs = [
        f"{code}:{area}"
        for code, areas in RULE_ACCOUNT_EXPECTATIONS.items()
        for area in sorted(areas)
        if (code, area) not in coverage
    ]
    if missing_pairs:
        raise AssertionError(f"rule accounts missing {len(missing_pairs)} pairs: {', '.join(missing_pairs[:10])}")
    print(f"RULE_ACCOUNT_OK rows={len(accounts)} pairs={len(coverage)}")


def _validate_template(env):
    company = env.company
    installed_l10n_co = bool(
        env["ir.module.module"].search_count([("name", "=", "l10n_co"), ("state", "=", "installed")])
    )
    print(
        "HR_CONFIG_CONTEXT",
        f"company={company.id}",
        f"name={company.name}",
        f"country={getattr(company.country_id, 'code', False)}",
        f"fiscal_country={getattr(company.account_fiscal_country_id, 'code', False)}",
        f"chart_template={company.chart_template}",
        f"l10n_co_installed={installed_l10n_co}",
    )

    settings = env["res.config.settings"].with_company(company).create({"company_id": company.id})

    try:
        with env.cr.savepoint():
            settings.apply_template_payroll_colombia()
            env.flush_all()

            if not company.aplicada:
                raise AssertionError("company.aplicada was not set to True")

            category_codes = _load_expected_values("category", "code")
            _assert_contains_all(
                "CATEGORY",
                category_codes,
                set(
                    env["hr.salary.rule.category"]
                    .search([("company_id", "=", company.id), ("code", "in", list(category_codes))])
                    .mapped("code")
                ),
            )

            work_entry_names = _load_expected_values("work_entry_type", "name")
            _assert_contains_all(
                "WORK_ENTRY",
                work_entry_names,
                set(
                    env["hr.work.entry.type"]
                    .search([("name", "in", list(work_entry_names))])
                    .mapped("name")
                ),
            )

            structure_type_names = _load_expected_values("structure_type", "name")
            _assert_contains_all(
                "STRUCTURE_TYPE",
                structure_type_names,
                set(
                    env["hr.payroll.structure.type"]
                    .search([("name", "in", list(structure_type_names))])
                    .mapped("name")
                ),
            )

            structure_names = _load_expected_values("structure", "name")
            structures = env["hr.payroll.structure"].search(
                [("company_id", "=", company.id), ("name", "in", list(structure_names))]
            )
            _assert_contains_all("STRUCTURE", structure_names, set(structures.mapped("name")))
            missing_inputs = structures.filtered(lambda struct: not struct.input_line_type_ids)
            if missing_inputs:
                raise AssertionError(
                    "structures without input_line_type_ids: "
                    + ", ".join(missing_inputs.mapped("name")[:10])
                )
            print(f"STRUCTURE_INPUTS_OK checked={len(structures)}")

            input_codes = _load_expected_values("input", "code")
            _assert_contains_all(
                "INPUT",
                input_codes,
                set(
                    env["hr.payslip.input.type"]
                    .search([("code", "in", list(input_codes))])
                    .mapped("code")
                ),
            )

            rule_codes = _load_expected_values("rule", "code")
            active_rules = env["hr.salary.rule"].search(
                [("company_id", "=", company.id), ("active", "=", True), ("code", "in", list(rule_codes))]
            )
            _assert_contains_all("RULE", rule_codes, set(active_rules.mapped("code")))
            archived_rules = env["hr.salary.rule"].search_count(
                [("company_id", "=", company.id), ("code", "like", "%_OLD"), ("active", "=", False)]
            )
            print(f"RULE_ARCHIVE_OK archived_old_rules={archived_rules}")

            _validate_rule_accounts(env, company)
            raise _RollbackTest
    except _RollbackTest:
        return


def main():
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
        try:
            _validate_template(env)
        finally:
            cr.rollback()


if __name__ == "__main__":
    main()
