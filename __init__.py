from . import models


def _post_init_hook(env):
    """Migra exclusion_groups legacy al nuevo modelo de reglas."""
    env['sembradora.config.accessory.line']._migrate_exclusion_groups()