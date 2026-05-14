import json
import logging
from pathlib import Path

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_payload(filename, key):
    data_path = DATA_DIR / filename
    if not data_path.exists():
        return []
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    return payload.get(key, [])


def _to_bool(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _to_float(value, default=0.0):
    if value in (None, ""):
        return default
    return float(value)


def _to_int(value, default=0):
    if value in (None, ""):
        return default
    return int(value)


def _country_co(env):
    return env["res.country"].search([("code", "=", "CO")], limit=1)


def _diff_values(record, values):
    updates = {}
    for field_name, value in values.items():
        if field_name not in record._fields:
            continue
        field = record._fields[field_name]
        current = record[field_name]
        if field.type == "many2one":
            current = current.id or False
            value = value or False
        elif field.type in ("float", "monetary"):
            current = float(current or 0.0)
            value = float(value or 0.0)
        elif field.type == "integer":
            current = int(current or 0)
            value = int(value or 0)
        elif field.type == "boolean":
            current = bool(current)
            value = bool(value)
        elif field.type in ("one2many", "many2many"):
            continue
        else:
            current = current or ""
            value = value or ""
        if current != value:
            updates[field_name] = value
    return updates


def _supported_values(model, values):
    return {field_name: value for field_name, value in values.items() if field_name in model._fields}


def _optional_domain(model, field_name, value, operator="="):
    if field_name not in model._fields:
        return []
    return [(field_name, operator, value)]


def _localization_domain(model, env, colombia=False):
    domain = []
    if "company_id" in model._fields:
        domain.append(("company_id", "=", env.company.id))
    elif colombia and "country_id" in model._fields:
        domain.append(("country_id", "=", colombia.id))
    return domain


def _merge_duplicate_salary_rule_categories(env):
    Category = env["hr.salary.rule.category"].with_context(active_test=False)
    Rule = env["hr.salary.rule"].with_context(active_test=False)
    colombia = _country_co(env)
    categories = Category.search(_localization_domain(Category, env, colombia), order="code, id")
    grouped = {}
    for category in categories:
        if not category.code:
            continue
        grouped.setdefault(category.code, Category.browse())
        grouped[category.code] |= category

    merged = 0
    for categories_by_code in grouped.values():
        if len(categories_by_code) < 2:
            continue
        keeper = categories_by_code[0]
        duplicates = categories_by_code - keeper
        if duplicates and "category_id" in Rule._fields:
            rules = Rule.search([("category_id", "in", duplicates.ids)])
            if rules:
                rules.write({"category_id": keeper.id})
        if duplicates and "parent_id" in Category._fields:
            children = Category.search([("parent_id", "in", duplicates.ids)])
            if children:
                children.write({"parent_id": keeper.id})
        duplicates.unlink()
        merged += len(duplicates)
    return merged


def ensure_work_entry_types(env):
    entries = _load_payload("hr_work_entry_type_data.json", "entry")
    if not entries:
        return 0, 0

    WorkEntryType = env["hr.work.entry.type"].with_context(active_test=False)
    colombia = _country_co(env)
    created = updated = 0

    for raw_values in entries:
        code = raw_values.get("code")
        name = raw_values.get("name") or code
        if not code:
            continue
        values = {
            "name": name,
            "code": code,
            "round_days": raw_values.get("round_days") or "NO",
        }
        if colombia and "country_id" in WorkEntryType._fields:
            values["country_id"] = colombia.id

        work_entry_type = WorkEntryType.search(["|", ("code", "=", code), ("name", "=", name)], limit=1)
        if work_entry_type:
            updates = _diff_values(work_entry_type, values)
            if updates:
                work_entry_type.write(updates)
                updated += 1
        else:
            WorkEntryType.create(_supported_values(WorkEntryType, values))
            created += 1

    return created, updated


def ensure_salary_rule_categories(env):
    categories = _load_payload("hr_salary_rule_category_data.json", "category")
    if not categories:
        return 0, 0

    Category = env["hr.salary.rule.category"].with_context(active_test=False)
    colombia = _country_co(env)
    created = updated = _merge_duplicate_salary_rule_categories(env)
    categories_by_code = {}

    for raw_values in categories:
        code = raw_values.get("code")
        if not code:
            continue
        domain = [("code", "=", code)] + _localization_domain(Category, env, colombia)
        category = Category.search(domain, limit=1)
        if not category:
            values = {
                "name": raw_values.get("name") or code,
                "code": code,
            }
            if "company_id" in Category._fields:
                values["company_id"] = env.company.id
            if colombia and "country_id" in Category._fields:
                values["country_id"] = colombia.id
            category = Category.create(
                _supported_values(Category, values)
            )
            created += 1
        categories_by_code[code] = category

    for raw_values in categories:
        code = raw_values.get("code")
        parent_code = raw_values.get("parent_id")
        category = categories_by_code.get(code)
        parent = categories_by_code.get(parent_code) if parent_code else False
        if category and parent and category.parent_id != parent:
            category.write({"parent_id": parent.id})
            updated += 1

    return created, updated


def ensure_structure_types(env):
    structure_types = _load_payload("hr_payroll_structure_type_data.json", "type")
    if not structure_types:
        return 0, 0

    StructureType = env["hr.payroll.structure.type"].with_context(active_test=False)
    WorkEntryType = env["hr.work.entry.type"].with_context(active_test=False)
    colombia = _country_co(env)
    created = updated = 0

    for raw_values in structure_types:
        name = raw_values.get("name")
        if not name:
            continue
        default_work_entry_type = WorkEntryType.search(
            [("name", "=", raw_values.get("default_work_entry_type_id"))], limit=1
        )
        values = {
            "name": name,
            "wage_type": raw_values.get("wage_type") or "monthly",
            "default_schedule_pay": raw_values.get("default_schedule_pay") or "monthly",
            "default_work_entry_type_id": default_work_entry_type.id,
        }
        if colombia and "country_id" in StructureType._fields:
            values["country_id"] = colombia.id

        structure_type = StructureType.search([("name", "=", name)], limit=1)
        if structure_type:
            updates = _diff_values(structure_type, values)
            if updates:
                structure_type.write(updates)
                updated += 1
        else:
            StructureType.create(_supported_values(StructureType, values))
            created += 1

    return created, updated


def ensure_structures(env):
    structures = _load_payload("hr_payroll_structure_data.json", "payroll")
    if not structures:
        return 0, 0

    Structure = env["hr.payroll.structure"].with_context(active_test=False)
    StructureType = env["hr.payroll.structure.type"].with_context(active_test=False)
    colombia = _country_co(env)
    created = updated = 0

    for raw_values in structures:
        name = raw_values.get("name")
        if not name:
            continue
        structure_type = StructureType.search([("name", "=", raw_values.get("type_id"))], limit=1)
        values = {
            "name": name,
            "type_id": structure_type.id,
            "active": True,
        }
        if colombia and "country_id" in Structure._fields:
            values["country_id"] = colombia.id

        domain = [("name", "=", name)] + _localization_domain(Structure, env, colombia)
        if structure_type and "type_id" in Structure._fields:
            domain.append(("type_id", "=", structure_type.id))
        structure = Structure.search(domain, limit=1)
        if structure:
            updates = _diff_values(structure, values)
            if updates:
                structure.write(updates)
                updated += 1
        else:
            Structure.create(_supported_values(Structure, values))
            created += 1

    return created, updated


def ensure_salary_rules(env):
    rules = _load_payload("hr_salary_rule_data.json", "rule")
    if not rules:
        return 0, 0

    Rule = env["hr.salary.rule"].with_context(active_test=False)
    Category = env["hr.salary.rule.category"].with_context(active_test=False)
    Structure = env["hr.payroll.structure"].with_context(active_test=False)
    colombia = _country_co(env)
    localization_domain_rule = _localization_domain(Rule, env, colombia)
    localization_domain_category = _localization_domain(Category, env, colombia)
    localization_domain_structure = _localization_domain(Structure, env, colombia)
    created = updated = 0

    for raw_values in rules:
        code = raw_values.get("code")
        struct_name = raw_values.get("struct_id")
        category_code = raw_values.get("category_id")
        if not code or not struct_name or not category_code:
            continue

        structure_domain = [("name", "=", struct_name)] + localization_domain_structure
        structure = Structure.search(structure_domain, limit=1)
        category_domain = [("code", "=", category_code)] + localization_domain_category
        category = Category.search(category_domain, limit=1)
        if not structure or not category:
            _logger.warning(
                "Skipping salary rule %s because structure %s or category %s is missing.",
                code,
                struct_name,
                category_code,
            )
            continue

        values = {
            "name": raw_values.get("name") or code,
            "code": code,
            "struct_id": structure.id,
            "sequence": _to_int(raw_values.get("sequence")),
            "appears_on_payslip": _to_bool(raw_values.get("appears_on_payslip")),
            "condition_range": raw_values.get("condition_range") or "",
            "amount_fix": _to_float(raw_values.get("amount_fix")),
            "amount_percentage": _to_float(raw_values.get("amount_percentage")),
            "condition_range_min": raw_values.get("condition_range_min") or "",
            "condition_select": raw_values.get("condition_select") or "none",
            "amount_percentage_base": raw_values.get("amount_percentage_base") or "",
            "amount_select": raw_values.get("amount_select") or "fix",
            "active": _to_bool(raw_values.get("active"), default=True),
            "condition_range_max": raw_values.get("condition_range_max") or "",
            "name": raw_values.get("name") or code,
            "condition_python": raw_values.get("condition_python") or "result = True",
            "amount_python_compute": raw_values.get("amount_python_compute") or "",
            "category_id": category.id,
            "quantity": raw_values.get("quantity") or "1.0",
            "origin_partner": raw_values.get("origin_partner") or False,
        }
        if colombia and "country_id" in Rule._fields:
            values["country_id"] = colombia.id
        if "company_id" in Rule._fields:
            values["company_id"] = env.company.id

        domain = [("code", "=", code), ("struct_id", "=", structure.id)] + localization_domain_rule
        rule = Rule.search(domain, limit=1)
        if rule:
            updates = _diff_values(rule, values)
            if updates:
                rule.write(updates)
                updated += 1
        else:
            Rule.create(_supported_values(Rule, values))
            created += 1

    return created, updated


def ensure_payslip_input_types(env):
    input_types = _load_payload("hr_payslip_input_type_data.json", "input")
    if not input_types:
        return 0, 0

    InputType = env["hr.payslip.input.type"].with_context(active_test=False)
    Structure = env["hr.payroll.structure"].with_context(active_test=False)
    colombia = _country_co(env)
    created = updated = 0

    for raw_values in input_types:
        code = raw_values.get("code")
        if not code:
            continue

        values = {
            "name": raw_values.get("name") or code,
            "code": code,
        }
        if colombia and "country_id" in InputType._fields:
            values["country_id"] = colombia.id

        struct_commands = False
        struct_name = raw_values.get("struct_ids")
        if struct_name and "struct_ids" in InputType._fields:
            structure_domain = [("name", "=", struct_name)] + _localization_domain(Structure, env, colombia)
            structures = Structure.search(structure_domain)
            if structures:
                struct_commands = [(6, 0, structures.ids)]

        input_type = InputType.search([("code", "=", code)], limit=1)
        if input_type:
            updates = _diff_values(input_type, values)
            if updates:
                input_type.write(updates)
                updated += 1
            if struct_commands:
                target_ids = set(struct_commands[0][2])
                current_ids = set(input_type.struct_ids.ids)
                if not target_ids.issubset(current_ids):
                    input_type.write({"struct_ids": [(6, 0, sorted(current_ids | target_ids))]})
                    updated += 1
        else:
            if struct_commands:
                values["struct_ids"] = struct_commands
            InputType.create(_supported_values(InputType, values))
            created += 1

    return created, updated


def ensure_localized_structure_assignment(env):
    structure_types = _load_payload("hr_payroll_structure_type_data.json", "type")
    structures = _load_payload("hr_payroll_structure_data.json", "payroll")
    if not structure_types or not structures:
        return 0, 0

    localized_type_name = structure_types[0].get("name")
    localized_structure_name = structures[0].get("name")
    localized_type = env["hr.payroll.structure.type"].with_context(active_test=False).search(
        [("name", "=", localized_type_name)],
        limit=1,
    )
    Structure = env["hr.payroll.structure"].with_context(active_test=False)
    colombia = _country_co(env)
    structure_domain = [("name", "=", localized_structure_name)] + _localization_domain(Structure, env, colombia)
    localized_structure = Structure.search(structure_domain, limit=1)
    if not localized_type or not localized_structure:
        return 0, 0

    updated_types = updated_contracts = 0
    if localized_type.default_struct_id != localized_structure:
        localized_type.write({"default_struct_id": localized_structure.id})
        updated_types += 1

    contract_model = "hr.contract" if "hr.contract" in env.registry else "hr.version"
    Contract = env[contract_model].with_context(active_test=False)
    contract_domain = []
    contract_domain += _optional_domain(Contract, "company_id", env.company.id)
    contract_domain += _optional_domain(Contract, "structure_type_id", localized_type.id, "!=")
    if "wage_type" in Contract._fields and "wage_type" in localized_type._fields:
        contract_domain.append(("wage_type", "=", localized_type.wage_type))
    if "schedule_pay" in Contract._fields and "default_schedule_pay" in localized_type._fields:
        contract_domain.append(("schedule_pay", "=", localized_type.default_schedule_pay))
    contracts = Contract.search(contract_domain)
    for contract in contracts:
        if contract.structure_type_id and contract.structure_type_id.name not in {"Employee", "Worker"}:
            continue
        contract.write({"structure_type_id": localized_type.id})
        updated_contracts += 1

    return updated_types, updated_contracts


def ensure_payroll_template(env):
    stats = {
        "work_entry_types": ensure_work_entry_types(env),
        "categories": ensure_salary_rule_categories(env),
        "structure_types": ensure_structure_types(env),
        "structures": ensure_structures(env),
        "rules": ensure_salary_rules(env),
        "input_types": ensure_payslip_input_types(env),
        "assignment": ensure_localized_structure_assignment(env),
    }
    _logger.info("Ensured l10n_co_payroll template data: %s", stats)
    return stats


def post_init_hook(env_or_cr, registry=None):
    if isinstance(env_or_cr, api.Environment):
        env = env_or_cr
    else:
        env = api.Environment(env_or_cr, SUPERUSER_ID, {})
    ensure_payroll_template(env)
