import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Delete table for removed models credito and cuota
    cr.execute("DROP TABLE IF EXISTS cuota CASCADE")
    cr.execute("DROP TABLE IF EXISTS credito CASCADE")
