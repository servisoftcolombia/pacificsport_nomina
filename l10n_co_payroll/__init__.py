# -*- coding: utf-8 -*-
from .hooks import post_init_hook
from . import models
from . import wizard
from odoo import api,fields, SUPERUSER_ID
import logging


_logger = logging.getLogger(__name__)
