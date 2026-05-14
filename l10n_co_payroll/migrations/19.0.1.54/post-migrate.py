import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Category = env["hr.salary.rule.category"].with_context(active_test=False)
    Rule = env["hr.salary.rule"].with_context(active_test=False)
    categories = Category.search([], order="company_id, code, id")
    grouped = {}

    for category in categories:
        if not category.code:
            continue
        company_id = category.company_id.id if "company_id" in Category._fields else False
        key = (company_id, category.code)
        grouped.setdefault(key, Category.browse())
        grouped[key] |= category

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

    if merged:
        _logger.info("Merged duplicated hr.salary.rule.category records: %s", merged)
