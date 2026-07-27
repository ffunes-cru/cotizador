from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SembradoraConfigAccessoryLine(models.Model):
    _name = 'sembradora.config.accessory.line'
    _description = 'Accesorio por Configuración con Precio'

    ext_id = fields.Char(string='ID Externo', readonly=False)

    config_id = fields.Many2one(
        'sembradora.config.rel',
        string='Configuración',
        required=True,
        ondelete='cascade')

    product_id = fields.Many2one(
        'product.product',
        string='Accesorio',
        required=True,
        domain=[("categ_id.name", "=", "Accesorio")])

    price = fields.Float(string='Precio en esta Configuración')

    # Relación Many2many directa con reglas
    rule_ids = fields.Many2many(
        'sembradora.accessory.rule',
        string='Reglas')

    is_trigger = fields.Boolean(
        string='Es Trigger',
        default=False,
        help='Indica si este accesorio habilita a los demás accesorios '
             'pertenecientes a sus reglas de inclusión al ser seleccionado.')

    # DEPRECADO: Se mantiene para migración. No usar en código nuevo.
    exclusion_group = fields.Char(
        string='Grupo de Exclusión (legacy)',
        help='DEPRECADO. Usar Reglas de Exclusión/Inclusión.')

    # Campo opcional: cantidad del accesorio para esta configuración.
    # Si se deja en 0 o vacío, se usa la lógica dinámica (get_acc_quan).
    quantity = fields.Float(
        string='Cantidad (opcional)',
        default=0,
        help='Si se especifica (> 0), se usa esta cantidad. '
             'Si se deja en 0, se calcula dinámicamente según la configuración.')

    def _migrate_exclusion_groups(self):
        """
        Migra los exclusion_group (Char) existentes a registros
        sembradora.accessory.rule con tipo exclusión y los vincula a rule_ids.
        """
        Rule = self.env['sembradora.accessory.rule']

        lines_to_migrate = self.search([
            ('exclusion_group', '!=', False),
            ('exclusion_group', '!=', ''),
            ('rule_ids', '=', False),
        ])

        if not lines_to_migrate:
            _logger.info("No hay exclusion_groups legacy para migrar.")
            return

        group_names = set(lines_to_migrate.mapped('exclusion_group'))
        _logger.info("Migrando %d exclusion_groups únicos: %s", len(group_names), group_names)

        rule_cache = {}
        for name in group_names:
            rule = Rule.search([('name', '=', name), ('rule_type', '=', 'exclusion')], limit=1)
            if not rule:
                rule = Rule.create({
                    'name': name,
                    'rule_type': 'exclusion',
                    'description': 'Migrado automáticamente desde exclusion_group legacy.',
                })
                _logger.info("Regla de exclusión creada: %s", name)
            rule_cache[name] = rule

        for line in lines_to_migrate:
            rule = rule_cache.get(line.exclusion_group)
            if rule:
                line.rule_ids = [(4, rule.id)]
                _logger.info("Migrada línea %s (accesorio: %s) → regla %s",
                             line.id, line.product_id.name, rule.name)
