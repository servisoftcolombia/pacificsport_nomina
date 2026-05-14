import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Delete record of the removed credit model in table ir_model
    cr.execute("DELETE FROM ir_model WHERE model = 'credito'")
